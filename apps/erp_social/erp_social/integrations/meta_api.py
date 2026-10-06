"""Minimal Meta Graph API client.

No Frappe imports: callers pass credentials in, so this module unit-tests without a bench.
Errors never include access tokens (requests puts the full URL, token included, in its messages).
"""

import json
from urllib.parse import urlencode

import requests

from erp_social.utils.signatures import meta_appsecret_proof

GRAPH_URL = "https://graph.facebook.com"
DIALOG_URL = "https://www.facebook.com"
DEFAULT_VERSION = "v26.0"
TIMEOUT = 20

# Permissions requested by "Connect Facebook Page".
LOGIN_SCOPES = (
	"pages_show_list",
	"pages_read_engagement",
	"pages_manage_metadata",
	"leads_retrieval",
	"pages_messaging",
	"instagram_basic",
	"instagram_manage_messages",
	"ads_management",
	"business_management",
)
# Page webhook fields our app subscribes each connected Page to.
PAGE_SUBSCRIBED_FIELDS = ("leadgen", "messages")
AUDIENCE_BATCH_SIZE = 10000


class MetaAPIError(Exception):
	def __init__(self, message, status_code=None, code=None):
		super().__init__(message)
		self.status_code = status_code
		self.code = code


class MetaClient:
	def __init__(self, app_id: str, app_secret: str, version: str | None = None, session=None):
		self.app_id = app_id
		self.app_secret = app_secret
		self.version = version or DEFAULT_VERSION
		self.http = session or requests

	# --- OAuth -------------------------------------------------------------------------

	def login_url(self, redirect_uri: str, state: str, scopes=LOGIN_SCOPES) -> str:
		query = urlencode(
			{
				"client_id": self.app_id,
				"redirect_uri": redirect_uri,
				"state": state,
				"response_type": "code",
				"scope": ",".join(scopes),
			}
		)
		return f"{DIALOG_URL}/{self.version}/dialog/oauth?{query}"

	def exchange_code(self, code: str, redirect_uri: str) -> dict:
		"""Code -> short-lived user token."""
		return self._get(
			"oauth/access_token",
			params={
				"client_id": self.app_id,
				"client_secret": self.app_secret,
				"redirect_uri": redirect_uri,
				"code": code,
			},
		)

	def long_lived_user_token(self, short_lived_token: str) -> dict:
		"""Short-lived user token -> ~60 day token. Page tokens derived from it don't expire."""
		return self._get(
			"oauth/access_token",
			params={
				"grant_type": "fb_exchange_token",
				"client_id": self.app_id,
				"client_secret": self.app_secret,
				"fb_exchange_token": short_lived_token,
			},
		)

	# --- Pages / ad accounts -----------------------------------------------------------

	def list_pages(self, user_token: str) -> list[dict]:
		data = self._get(
			"me/accounts",
			token=user_token,
			params={
				"fields": "id,name,access_token,tasks,instagram_business_account{id,username}",
				"limit": 200,
			},
		)
		return data.get("data") or []

	def list_ad_accounts(self, user_token: str) -> list[dict]:
		data = self._get(
			"me/adaccounts",
			token=user_token,
			params={"fields": "account_id,name,account_status", "limit": 200},
		)
		return data.get("data") or []

	def subscribe_page(self, page_id: str, page_token: str, fields=PAGE_SUBSCRIBED_FIELDS) -> dict:
		return self._post(
			f"{page_id}/subscribed_apps", token=page_token, data={"subscribed_fields": ",".join(fields)}
		)

	def unsubscribe_page(self, page_id: str, page_token: str) -> dict:
		return self._request("DELETE", f"{page_id}/subscribed_apps", token=page_token)

	# --- Leads -------------------------------------------------------------------------

	def get_lead(self, leadgen_id: str, page_token: str) -> dict:
		return self._get(
			leadgen_id,
			token=page_token,
			params={"fields": "field_data,created_time,ad_id,ad_name,form_id,campaign_name"},
		)

	# --- Messaging (Messenger + Instagram) ---------------------------------------------

	def get_profile(self, user_id: str, page_token: str, platform: str) -> dict:
		fields = "name,username" if platform == "Instagram" else "first_name,last_name"
		return self._get(user_id, token=page_token, params={"fields": fields})

	def send_message(self, page_id: str, page_token: str, recipient_id: str, text: str) -> dict:
		"""Reply through the Page. Works for Messenger PSIDs and Instagram IGSIDs alike."""
		return self._post(
			f"{page_id}/messages",
			token=page_token,
			json_body={
				"recipient": {"id": recipient_id},
				"messaging_type": "RESPONSE",
				"message": {"text": text},
			},
		)

	# --- Custom Audiences --------------------------------------------------------------

	def create_custom_audience(
		self, ad_account_id: str, name: str, user_token: str, description: str = ""
	) -> str:
		data = self._post(
			f"act_{ad_account_id.removeprefix('act_')}/customaudiences",
			token=user_token,
			data={
				"name": name,
				"subtype": "CUSTOM",
				"description": description,
				"customer_file_source": "USER_PROVIDED_ONLY",
			},
		)
		return str(data["id"])

	def add_audience_users(self, audience_id: str, rows: list[list[str]], user_token: str) -> int:
		"""Upload pre-hashed [EMAIL, PHONE] rows in batches. Returns rows accepted by Meta."""
		received = 0
		for start in range(0, len(rows), AUDIENCE_BATCH_SIZE):
			batch = rows[start : start + AUDIENCE_BATCH_SIZE]
			data = self._post(
				f"{audience_id}/users",
				token=user_token,
				data={"payload": json.dumps({"schema": ["EMAIL", "PHONE"], "data": batch})},
			)
			received += int(data.get("num_received") or 0)
		return received

	# --- HTTP --------------------------------------------------------------------------

	def _get(self, path, token=None, params=None):
		return self._request("GET", path, token=token, params=params)

	def _post(self, path, token=None, data=None, json_body=None):
		return self._request("POST", path, token=token, data=data, json_body=json_body)

	def _request(self, method, path, token=None, params=None, data=None, json_body=None):
		params = dict(params or {})
		if token:
			params["access_token"] = token
			params["appsecret_proof"] = meta_appsecret_proof(token, self.app_secret)

		failure = None
		try:
			response = self.http.request(
				method,
				f"{GRAPH_URL}/{self.version}/{path.lstrip('/')}",
				params=params,
				data=data,
				json=json_body,
				timeout=TIMEOUT,
			)
		except requests.RequestException as e:
			failure = type(e).__name__
		if failure:
			# Raised outside the except block so the original exception (whose message holds the
			# full URL including access_token) isn't chained into stored tracebacks.
			raise MetaAPIError(f"Could not reach the Graph API ({failure}).")

		try:
			body = response.json()
		except ValueError:
			body = {}
		if not response.ok or "error" in body:
			error = body.get("error") or {}
			message = error.get("message") or response.text[:300]
			raise MetaAPIError(
				f"Graph API returned {response.status_code}: {message}",
				status_code=response.status_code,
				code=error.get("code"),
			)
		return body
