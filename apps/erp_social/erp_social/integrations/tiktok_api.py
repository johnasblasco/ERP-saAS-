"""Minimal TikTok API for Business (Marketing API v1.3) client.

No Frappe imports, so it unit-tests without a bench. TikTok answers most errors with HTTP 200 and a
non-zero `code`; both cases raise TikTokAPIError. Errors never include access tokens or secrets.

Endpoint shapes follow TikTok's official SDK specs (github.com/tiktok/tiktok-business-api-sdk).
"""

import hashlib
from urllib.parse import urlencode

import requests

API_URL = "https://business-api.tiktok.com/open_api/v1.3"
AUTH_URL = "https://business-api.tiktok.com/portal/auth"
TIMEOUT = 30


class TikTokAPIError(Exception):
	def __init__(self, message, code=None):
		super().__init__(message)
		self.code = code


class TikTokClient:
	def __init__(self, app_id: str, app_secret: str, session=None):
		self.app_id = app_id
		self.app_secret = app_secret
		self.http = session or requests

	# --- OAuth (advertiser authorization) ----------------------------------------------

	def login_url(self, redirect_uri: str, state: str) -> str:
		query = urlencode({"app_id": self.app_id, "redirect_uri": redirect_uri, "state": state})
		return f"{AUTH_URL}?{query}"

	def exchange_auth_code(self, auth_code: str) -> dict:
		"""-> {access_token, advertiser_ids, scope, ...}"""
		return self._request(
			"POST",
			"oauth2/access_token/",
			json_body={"app_id": self.app_id, "secret": self.app_secret, "auth_code": auth_code},
		)

	def list_advertisers(self, access_token: str) -> list[dict]:
		data = self._request(
			"GET",
			"oauth2/advertiser/get/",
			params={"app_id": self.app_id, "secret": self.app_secret},
			token=access_token,
		)
		return data.get("list") or []

	# --- Lead webhooks -----------------------------------------------------------------

	def subscribe_leads(self, advertiser_id: str, access_token: str, callback_url: str) -> str:
		data = self._request(
			"POST",
			"subscription/subscribe/",
			json_body={
				"app_id": self.app_id,
				"secret": self.app_secret,
				"subscribe_entity": "LEAD",
				"callback_url": callback_url,
				"subscription_detail": {
					"access_token": access_token,
					"lead_source": "INSTANT_FORM",
					"advertiser_id": advertiser_id,
				},
			},
		)
		return str(data.get("subscription_id") or "")

	def unsubscribe(self, subscription_id: str) -> None:
		self._request(
			"POST",
			"subscription/unsubscribe/",
			json_body={"app_id": self.app_id, "secret": self.app_secret, "subscription_id": subscription_id},
		)

	# --- Custom Audiences --------------------------------------------------------------

	def upload_audience_file(
		self, advertiser_id: str, access_token: str, content: bytes, calculate_type: str
	) -> str:
		"""Upload one hashed-ID-per-line file. Returns the file_path to create/update an audience with."""
		data = self._request(
			"POST",
			"dmp/custom_audience/file/upload/",
			token=access_token,
			form={
				"advertiser_id": advertiser_id,
				"calculate_type": calculate_type,
				"file_signature": hashlib.md5(content).hexdigest(),
			},
			files={"file": ("audience.txt", content, "text/plain")},
		)
		return data["file_path"]

	def create_audience(
		self, advertiser_id: str, access_token: str, name: str, file_paths: list[str], calculate_type: str
	) -> str:
		data = self._request(
			"POST",
			"dmp/custom_audience/create/",
			token=access_token,
			json_body={
				"advertiser_id": advertiser_id,
				"custom_audience_name": name[:128],
				"calculate_type": calculate_type,
				"file_paths": file_paths,
			},
		)
		return str(data["custom_audience_id"])

	def update_audience(
		self,
		advertiser_id: str,
		access_token: str,
		audience_id: str,
		file_paths: list[str],
		action: str = "APPEND",
	) -> None:
		self._request(
			"POST",
			"dmp/custom_audience/update/",
			token=access_token,
			json_body={
				"advertiser_id": advertiser_id,
				"custom_audience_id": audience_id,
				"file_paths": file_paths,
				"action": action,
			},
		)

	# --- HTTP --------------------------------------------------------------------------

	def _request(self, method, path, token=None, params=None, json_body=None, form=None, files=None):
		headers = {"Access-Token": token} if token else {}
		failure = None
		try:
			response = self.http.request(
				method,
				f"{API_URL}/{path}",
				headers=headers,
				params=params,
				json=json_body,
				data=form,
				files=files,
				timeout=TIMEOUT,
			)
		except requests.RequestException as e:
			failure = type(e).__name__
		if failure:
			raise TikTokAPIError(f"Could not reach the TikTok API ({failure}).")

		try:
			body = response.json()
		except ValueError:
			raise TikTokAPIError(
				f"TikTok API returned {response.status_code} with a non-JSON body."
			) from None
		code = body.get("code")
		if not response.ok or code not in (0, None):
			raise TikTokAPIError(
				f"TikTok API error {code}: {body.get('message') or response.status_code}", code=code
			)
		return body.get("data") or {}
