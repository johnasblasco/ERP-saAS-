"""Public webhook endpoints for social platforms.

Each tenant site exposes its own URLs, e.g.
	https://<tenant>/api/method/erp_social.api.webhooks.meta
	https://<tenant>/api/method/erp_social.api.webhooks.tiktok

Deliveries are verified against the matching Social Platform Account's secret,
logged as Social Lead Events, and processed in a background job so the
platform gets a fast 200.
"""

import hmac
import json

import frappe
from werkzeug.wrappers import Response

from erp_social.utils.meta_leads import extract_leadgen_changes
from erp_social.utils.signatures import verify_meta_signature, verify_tiktok_signature

ACCOUNT = "Social Platform Account"
EVENT = "Social Lead Event"
META_PLATFORMS = ("Facebook", "Instagram")


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def meta(**kwargs):
	"""Meta (Facebook / Instagram) Page webhook: subscription check (GET) and lead deliveries (POST)."""
	if frappe.request.method == "GET":
		return _meta_verify_subscription()
	return _meta_receive()


@frappe.whitelist(allow_guest=True, methods=["POST"])
def tiktok(**kwargs):
	"""TikTok webhook: verifies the signature and logs the event.

	TODO: map TikTok lead payloads to Leads once the lead form webhook is configured.
	"""
	body = frappe.request.get_data() or b""
	header = frappe.get_request_header("TikTok-Signature")

	account = next(
		(
			acc
			for acc in _enabled_accounts(("TikTok",))
			if verify_tiktok_signature(body, header, _secret(acc, "app_secret"))
		),
		None,
	)
	if not account:
		return _text("invalid signature", 403)

	payload = _parse_json(body)
	_log_event(
		platform="TikTok",
		account=account,
		event_type=str(payload.get("event") or "unknown"),
		external_id=str(payload.get("log_id") or ""),
		payload=payload,
	)
	return _text("EVENT_RECEIVED")


def _meta_verify_subscription():
	args = frappe.local.form_dict
	mode, token, challenge = args.get("hub.mode"), args.get("hub.verify_token"), args.get("hub.challenge")
	if mode == "subscribe" and token and challenge:
		for account in _enabled_accounts(META_PLATFORMS):
			expected = _secret(account, "verify_token")
			if expected and hmac.compare_digest(expected, token):
				return _text(challenge)
	return _text("verification failed", 403)


def _meta_receive():
	body = frappe.request.get_data() or b""
	header = frappe.get_request_header("X-Hub-Signature-256")
	payload = _parse_json(body)

	accounts = {acc.external_id: acc for acc in _enabled_accounts(META_PLATFORMS)}
	verified = {}  # page_id -> bool, so each secret is checked once per delivery
	accepted = 0

	for change in extract_leadgen_changes(payload):
		account = accounts.get(change["page_id"])
		if not account:
			continue
		if change["page_id"] not in verified:
			verified[change["page_id"]] = verify_meta_signature(body, header, _secret(account, "app_secret"))
		if not verified[change["page_id"]]:
			continue

		accepted += 1
		if _already_logged(META_PLATFORMS, change["leadgen_id"]):
			continue  # Meta retries deliveries; one event per lead is enough.

		event = _log_event(
			platform=account.platform,
			account=account,
			event_type="leadgen",
			external_id=change["leadgen_id"],
			payload=change["raw"],
		)
		frappe.enqueue(
			"erp_social.social_integration.lead_sync.process_meta_lead_event",
			event_name=event.name,
			enqueue_after_commit=True,
			deduplicate=True,
			job_id=f"erp_social::meta_lead::{event.name}",
		)

	if verified and not any(verified.values()):
		return _text("invalid signature", 403)
	# 200 even when nothing matched (e.g. a page with no account here) so Meta doesn't retry forever.
	return _text("EVENT_RECEIVED" if accepted else "IGNORED")


def _enabled_accounts(platforms):
	return frappe.get_all(
		ACCOUNT,
		filters={"enabled": 1, "platform": ("in", platforms)},
		fields=["name", "platform", "external_id"],
	)


def _secret(account, fieldname):
	from frappe.utils.password import get_decrypted_password

	return get_decrypted_password(ACCOUNT, account.name, fieldname, raise_exception=False) or ""


def _already_logged(platforms, external_id):
	return frappe.db.exists(
		EVENT,
		{"platform": ("in", platforms), "external_id": external_id, "status": ("!=", "Failed")},
	)


def _log_event(platform, account, event_type, external_id, payload):
	return frappe.get_doc(
		{
			"doctype": EVENT,
			"platform": platform,
			"account": account.name,
			"event_type": event_type,
			"external_id": external_id,
			"status": "Received",
			"payload": json.dumps(payload, indent=1, default=str),
		}
	).insert(ignore_permissions=True)


def _parse_json(body):
	try:
		data = json.loads(body or b"{}")
	except ValueError:
		return {}
	return data if isinstance(data, dict) else {}


def _text(body, status=200):
	return Response(body, status=status, mimetype="text/plain")
