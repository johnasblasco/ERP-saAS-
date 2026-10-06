"""Receive every Meta webhook for the shared app and forward it to the tenant sites it's about.

Meta allows one callback URL per app, so with one app serving all tenants the control site is that
URL. The delivery is verified here, then forwarded byte-for-byte with its signature so each tenant
verifies it again with the same app secret (common_site_config `erp_social_meta_app_secret`).
"""

import hashlib
import hmac
import time

import frappe
import requests
from werkzeug.wrappers import Response

from saas_control.utils import meta_entry_ids, verify_meta_signature

FORWARD_PATH = "/api/method/erp_social.api.webhooks.meta"
NOT_RECEIVING = ("Pending Verification", "Queued", "Provisioning", "Failed", "Archived")
RETRY_DELAYS = (0, 2, 5, 15)


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def meta(**kwargs):
	if frappe.request.method == "GET":
		args = frappe.local.form_dict
		expected = frappe.conf.get("erp_social_meta_verify_token") or ""
		token = args.get("hub.verify_token") or ""
		if args.get("hub.mode") == "subscribe" and expected and hmac.compare_digest(expected, token):
			return _text(args.get("hub.challenge") or "")
		return _text("verification failed", 403)

	body = frappe.request.get_data() or b""
	signature = frappe.get_request_header("X-Hub-Signature-256")
	if not verify_meta_signature(body, signature, frappe.conf.get("erp_social_meta_app_secret") or ""):
		return _text("invalid signature", 403)

	ids = meta_entry_ids(body)
	tenants = set()
	if ids:
		tenants = set(
			frappe.get_all(
				"Tenant Social Route",
				filters={"platform": "Meta", "external_id": ("in", ids)},
				pluck="tenant",
			)
		)
	digest = hashlib.sha256(body).hexdigest()[:16]
	for tenant in sorted(tenants):
		frappe.enqueue(
			forward_delivery,
			tenant_name=tenant,
			body=body.decode("utf-8"),
			signature=signature,
			job_id=f"saas_control::meta::{tenant}::{digest}",
			deduplicate=True,
		)
	return _text("EVENT_RECEIVED" if tenants else "IGNORED")


def forward_delivery(tenant_name: str, body: str, signature: str):
	row = frappe.db.get_value("Tenant", tenant_name, ["status", "site_url"], as_dict=True)
	if not row or row.status in NOT_RECEIVING:
		return
	last_error = None
	for delay in RETRY_DELAYS:
		time.sleep(delay)
		try:
			response = requests.post(
				row.site_url + FORWARD_PATH,
				data=body.encode("utf-8"),
				headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
				timeout=15,
			)
		except requests.RequestException as e:
			last_error = type(e).__name__
			continue
		if response.ok or 400 <= response.status_code < 500:
			return  # delivered, or the tenant rejected it for good (retrying won't help)
		last_error = f"HTTP {response.status_code}"
	frappe.log_error(
		title=f"Meta webhook not delivered to {tenant_name}", message=f"Last error: {last_error}"
	)


def _text(body, status=200):
	return Response(body, status=status, mimetype="text/plain")
