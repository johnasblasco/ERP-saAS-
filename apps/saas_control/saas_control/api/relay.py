"""OAuth redirect relay. Meta and TikTok need exact redirect URIs registered on the app, which can't
list every tenant, so the shared app redirects here and we bounce the browser to the tenant named in
the OAuth `state` ("<site>~<random>"). Only registered, live tenant sites are valid targets, so this
can't be used as an open redirect; the tenant then checks the state against its own cache.
"""

from urllib.parse import urlencode

import frappe
from frappe import _
from werkzeug.utils import redirect
from werkzeug.wrappers import Response

LIVE = ("Trial", "Active", "Past Due")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def meta_oauth(**kwargs):
	return _relay("erp_social.api.oauth.meta_callback")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def tiktok_oauth(**kwargs):
	return _relay("erp_social.api.oauth.tiktok_callback")


def _relay(method: str):
	args = {k: v for k, v in frappe.request.args.items()}
	site, sep, _token = (args.get("state") or "").partition("~")
	site_url = sep and frappe.db.get_value("Tenant", {"site_name": site, "status": ("in", LIVE)}, "site_url")
	if not site_url:
		message = frappe.utils.escape_html(
			_("We couldn't tell which workspace started this connection. Start again from Social Connect.")
		)
		return Response(
			f"<!doctype html><title>{_('Link expired')}</title><p>{message}</p>", 400, mimetype="text/html"
		)
	return redirect(f"{site_url}/api/method/{method}?{urlencode(args)}")
