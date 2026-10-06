""" "Connect Facebook Page" and "Connect TikTok" OAuth flows.

1. `*_login_url` (System Manager) creates a single-use state bound to the user and returns the
   platform's consent URL.
2. The platform redirects to `*_callback` (directly, or via the SaaS control site's relay). The
   callback checks the state, exchanges the code for tokens and parks the result server-side under
   a random key for 30 minutes - tokens never reach the browser.
3. The Social Connect page lists what was authorized (`*_pending`) and the user picks which Pages /
   advertisers to connect (`*_connect`), which creates the accounts and subscribes their webhooks.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime
from werkzeug.utils import redirect

from erp_social.integrations import config
from erp_social.integrations.meta_api import MetaAPIError
from erp_social.integrations.tiktok_api import TikTokAPIError

ACCOUNT = "Social Platform Account"
CONNECT_PAGE = "/desk/social-connect"
STATE_TTL = 15 * 60
PENDING_TTL = 30 * 60


# --- Meta ----------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def meta_login_url():
	frappe.only_for("System Manager")
	return config.meta_client().login_url(config.meta_oauth_redirect_uri(), _new_state("meta"))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def meta_callback(code=None, state=None, error=None, error_description=None, **kwargs):
	if guest := _require_login():
		return guest
	try:
		_consume_state(state, "meta")
		if error or not code:
			frappe.throw(error_description or error or _("Facebook did not return an authorization code."))
		client = config.meta_client()
		short = client.exchange_code(code, config.meta_oauth_redirect_uri())
		long = client.long_lived_user_token(short["access_token"])
		user_token = long["access_token"]
		pages = client.list_pages(user_token)
		try:
			ad_accounts = client.list_ad_accounts(user_token)
		except MetaAPIError:
			ad_accounts = []  # ads permissions are optional; audiences just won't be available
	except (MetaAPIError, frappe.ValidationError) as e:
		return _back(error=str(e))

	expires_in = int(long.get("expires_in") or 0)
	key = _store_pending(
		"meta",
		{
			"user_token": user_token,
			"user_token_expires_on": str(add_to_date(now_datetime(), seconds=expires_in))
			if expires_in
			else None,
			"pages": pages,
			"ad_accounts": ad_accounts,
		},
	)
	return _back(pending=key, platform="meta")


@frappe.whitelist()
def meta_pending(key: str):
	frappe.only_for("System Manager")
	data = _get_pending(key, "meta")
	connected = set(frappe.get_all(ACCOUNT, filters={"platform": "Facebook"}, pluck="external_id"))
	return {
		"pages": [
			{
				"id": p["id"],
				"name": p.get("name"),
				"instagram_username": (p.get("instagram_business_account") or {}).get("username"),
				"connected": p["id"] in connected,
			}
			for p in data["pages"]
		],
		"ad_accounts": [{"id": a.get("account_id"), "name": a.get("name")} for a in data["ad_accounts"]],
	}


@frappe.whitelist(methods=["POST"])
def meta_connect(key: str, page_ids, ad_account_id: str | None = None):
	frappe.only_for("System Manager")
	data = _get_pending(key, "meta")
	page_ids = set(_as_list(page_ids))
	client = config.meta_client()
	results = []

	for page in data["pages"]:
		if page["id"] not in page_ids:
			continue
		instagram = page.get("instagram_business_account") or {}
		account = _upsert_account(
			"Facebook",
			page["id"],
			page.get("name") or page["id"],
			{
				"access_token": page["access_token"],
				"user_access_token": data["user_token"],
				"token_expires_on": data["user_token_expires_on"],
				"instagram_account_id": instagram.get("id"),
				"instagram_username": instagram.get("username"),
				"ad_account_id": ad_account_id,
			},
		)
		results.append(
			_subscribe(account, lambda acc=account, p=page: client.subscribe_page(p["id"], p["access_token"]))
		)

	_drop_pending(key)
	return results


# --- TikTok --------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def tiktok_login_url():
	frappe.only_for("System Manager")
	return config.tiktok_client().login_url(config.tiktok_oauth_redirect_uri(), _new_state("tiktok"))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def tiktok_callback(auth_code=None, code=None, state=None, **kwargs):
	if guest := _require_login():
		return guest
	try:
		_consume_state(state, "tiktok")
		auth_code = auth_code or code
		if not auth_code:
			frappe.throw(_("TikTok did not return an authorization code."))
		client = config.tiktok_client()
		token = client.exchange_auth_code(auth_code)
		access_token = token["access_token"]
		try:
			advertisers = client.list_advertisers(access_token)
		except TikTokAPIError:
			advertisers = []
		names = {str(a.get("advertiser_id")): a.get("advertiser_name") for a in advertisers}
	except (TikTokAPIError, frappe.ValidationError, KeyError) as e:
		return _back(error=str(e) if not isinstance(e, KeyError) else _("Unexpected response from TikTok."))

	key = _store_pending(
		"tiktok",
		{
			"access_token": access_token,
			"advertisers": [
				{"id": str(adv_id), "name": names.get(str(adv_id)) or str(adv_id)}
				for adv_id in token.get("advertiser_ids") or names.keys()
			],
		},
	)
	return _back(pending=key, platform="tiktok")


@frappe.whitelist()
def tiktok_pending(key: str):
	frappe.only_for("System Manager")
	data = _get_pending(key, "tiktok")
	connected = set(frappe.get_all(ACCOUNT, filters={"platform": "TikTok"}, pluck="external_id"))
	return {"advertisers": [{**a, "connected": a["id"] in connected} for a in data["advertisers"]]}


@frappe.whitelist(methods=["POST"])
def tiktok_connect(key: str, advertiser_ids):
	frappe.only_for("System Manager")
	data = _get_pending(key, "tiktok")
	wanted = set(_as_list(advertiser_ids))
	client = config.tiktok_client()
	callback_url = config.tiktok_webhook_url()
	results = []

	for adv in data["advertisers"]:
		if adv["id"] not in wanted:
			continue
		account = _upsert_account("TikTok", adv["id"], adv["name"], {"access_token": data["access_token"]})

		def subscribe(acc=account, adv_id=adv["id"]):
			if acc.tiktok_subscription_id:
				return
			acc.db_set(
				"tiktok_subscription_id", client.subscribe_leads(adv_id, data["access_token"], callback_url)
			)

		results.append(_subscribe(account, subscribe))

	_drop_pending(key)
	return results


# --- Status for the Social Connect page ----------------------------------------------------


@frappe.whitelist()
def overview():
	frappe.only_for(("System Manager", "Sales Manager"))
	meta, tiktok = config.meta_app(), config.tiktok_app()
	accounts = frappe.get_all(
		ACCOUNT,
		fields=[
			"name",
			"platform",
			"external_id",
			"enabled",
			"webhook_subscribed",
			"instagram_username",
			"connection_method",
			"token_expires_on",
		],
		order_by="platform, account_name",
	)
	counts = {
		(r.account, r.status): r.count
		for r in frappe.get_all(
			"Social Lead Event",
			fields=["account", "status", {"COUNT": "*", "as": "count"}],
			group_by="account, status",
		)
	}
	for acc in accounts:
		acc["processed"] = counts.get((acc.name, "Processed"), 0)
		acc["failed"] = counts.get((acc.name, "Failed"), 0)
	return {
		"meta_ready": bool(meta["app_id"] and meta["app_secret"]),
		"tiktok_ready": bool(tiktok["app_id"] and tiktok["app_secret"]),
		"managed": bool(config.control_plane()),
		"meta_webhook_url": config.meta_webhook_url(),
		"meta_redirect_uri": config.meta_oauth_redirect_uri(),
		"tiktok_redirect_uri": config.tiktok_oauth_redirect_uri(),
		"accounts": accounts,
	}


# --- helpers -------------------------------------------------------------------------------


def _new_state(platform: str) -> str:
	token = frappe.generate_hash(length=32)
	# With a control plane the relay needs to know which tenant to send the browser back to.
	state = f"{frappe.local.site}~{token}" if config.control_plane() else token
	frappe.cache.set_value(
		f"erp_social:oauth_state:{state}",
		{"user": frappe.session.user, "platform": platform},
		expires_in_sec=STATE_TTL,
	)
	return state


def _consume_state(state, platform):
	key = f"erp_social:oauth_state:{state}"
	data = frappe.cache.get_value(key) if state else None
	frappe.cache.delete_value(key)
	if not data or data.get("platform") != platform or data.get("user") != frappe.session.user:
		frappe.throw(_("This connection link expired or belongs to another user. Start again."))


def _store_pending(platform, data) -> str:
	key = frappe.generate_hash(length=32)
	frappe.cache.set_value(
		f"erp_social:oauth_pending:{key}",
		{"platform": platform, "user": frappe.session.user, **data},
		expires_in_sec=PENDING_TTL,
	)
	return key


def _get_pending(key, platform) -> dict:
	data = frappe.cache.get_value(f"erp_social:oauth_pending:{key}") if key else None
	if not data or data.get("platform") != platform or data.get("user") != frappe.session.user:
		frappe.throw(_("This connection expired. Start again."))
	return data


def _drop_pending(key):
	frappe.cache.delete_value(f"erp_social:oauth_pending:{key}")


def _upsert_account(platform, external_id, display_name, values):
	name = frappe.db.get_value(ACCOUNT, {"platform": platform, "external_id": external_id})
	account = frappe.get_doc(ACCOUNT, name) if name else frappe.new_doc(ACCOUNT)
	if not name:
		account_name = display_name
		if frappe.db.exists(ACCOUNT, account_name):
			account_name = f"{display_name} ({external_id})"
		account.update({"account_name": account_name, "platform": platform, "external_id": external_id})
	account.update({k: v for k, v in values.items() if v is not None})
	account.update({"enabled": 1, "connection_method": "OAuth"})
	account.save()
	return account


def _subscribe(account, subscribe) -> dict:
	try:
		subscribe()
	except (MetaAPIError, TikTokAPIError) as e:
		account.db_set("webhook_subscribed", 0)
		return {"account": account.name, "ok": False, "error": str(e)}
	account.db_set("webhook_subscribed", 1)
	return {"account": account.name, "ok": True}


def _as_list(value) -> list[str]:
	if isinstance(value, str):
		value = json.loads(value) if value.startswith("[") else [value]
	return [str(v) for v in value or []]


def _require_login():
	if frappe.session.user == "Guest":
		return redirect(f"/login?redirect-to={CONNECT_PAGE}")


def _back(**params):
	from urllib.parse import urlencode

	return redirect(f"{CONNECT_PAGE}?{urlencode(params)}")
