"""Where credentials and URLs come from.

Platform app credentials (Meta App / TikTok app) are read from Social Integration Settings and fall
back to site_config / common_site_config keys, so a SaaS operator can configure one app for every
tenant on the bench:

	erp_social_meta_app_id, erp_social_meta_app_secret, erp_social_meta_verify_token,
	erp_social_meta_graph_api_version, erp_social_tiktok_app_id, erp_social_tiktok_app_secret

When the site belongs to a SaaS control plane (site_config `saas_control_url` + `saas_tenant_key`),
Meta webhooks and OAuth redirects go through the control site, which owns the app-level URLs.
"""

import frappe
from frappe import _
from frappe.utils import get_url
from frappe.utils.password import get_decrypted_password

from erp_social.integrations.meta_api import DEFAULT_VERSION, MetaClient
from erp_social.integrations.tiktok_api import TikTokClient

SETTINGS = "Social Integration Settings"


def _setting(fieldname: str, password: bool = False) -> str:
	value = None
	if password:
		value = get_decrypted_password(SETTINGS, SETTINGS, fieldname, raise_exception=False)
	else:
		value = frappe.db.get_single_value(SETTINGS, fieldname)
	return (value or frappe.conf.get(f"erp_social_{fieldname}") or "").strip()


def meta_app() -> dict:
	return {
		"app_id": _setting("meta_app_id"),
		"app_secret": _setting("meta_app_secret", password=True),
		"verify_token": _setting("meta_verify_token", password=True),
		"version": _setting("meta_graph_api_version") or DEFAULT_VERSION,
	}


def tiktok_app() -> dict:
	return {
		"app_id": _setting("tiktok_app_id"),
		"app_secret": _setting("tiktok_app_secret", password=True),
	}


def meta_client(account=None) -> MetaClient:
	"""Client for the account's own app (bring-your-own app) or the shared app."""
	app = meta_app()
	app_id = (account and account.app_id) or app["app_id"]
	app_secret = (account and account.get_password("app_secret", raise_exception=False)) or app["app_secret"]
	if not (app_id and app_secret):
		frappe.throw(_("Set the Meta App ID and App Secret in Social Integration Settings."))
	return MetaClient(app_id, app_secret, app["version"])


def tiktok_client() -> TikTokClient:
	app = tiktok_app()
	if not (app["app_id"] and app["app_secret"]):
		frappe.throw(_("Set the TikTok App ID and Secret in Social Integration Settings."))
	return TikTokClient(app["app_id"], app["app_secret"])


def tiktok_webhook_token() -> str:
	"""Secret embedded in the TikTok callback URL; TikTok lead webhooks carry no signature."""
	token = get_decrypted_password(SETTINGS, SETTINGS, "tiktok_webhook_token", raise_exception=False)
	if not token:
		token = frappe.generate_hash(length=40)
		settings = frappe.get_single(SETTINGS)
		settings.tiktok_webhook_token = token
		settings.save(ignore_permissions=True)
	return token


# --- Control plane -------------------------------------------------------------------------


def control_plane() -> dict | None:
	url, key = frappe.conf.get("saas_control_url"), frappe.conf.get("saas_tenant_key")
	if url and key:
		return {"url": url.rstrip("/"), "key": key, "site": frappe.local.site}
	return None


def meta_oauth_redirect_uri() -> str:
	if cp := control_plane():
		return f"{cp['url']}/api/method/saas_control.api.relay.meta_oauth"
	return f"{get_url()}/api/method/erp_social.api.oauth.meta_callback"


def tiktok_oauth_redirect_uri() -> str:
	if cp := control_plane():
		return f"{cp['url']}/api/method/saas_control.api.relay.tiktok_oauth"
	return f"{get_url()}/api/method/erp_social.api.oauth.tiktok_callback"


def meta_webhook_url() -> str:
	if cp := control_plane():
		return f"{cp['url']}/api/method/saas_control.api.router.meta"
	return f"{get_url()}/api/method/erp_social.api.webhooks.meta"


def tiktok_webhook_url() -> str:
	return f"{get_url()}/api/method/erp_social.api.webhooks.tiktok?token={tiktok_webhook_token()}"
