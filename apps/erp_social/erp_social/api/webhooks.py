"""Public webhook endpoints for social platforms.

	/api/method/erp_social.api.webhooks.meta     Facebook / Instagram: leads + DMs (GET = verification)
	/api/method/erp_social.api.webhooks.tiktok   TikTok lead forms (?token=<secret>)

Meta deliveries are signed (X-Hub-Signature-256) with the app secret; under a SaaS control plane
the control site's router forwards them here unchanged, signature included. TikTok lead webhooks
carry no signature, so the callback URL registered with TikTok contains a per-site secret token.

Each delivery is logged as a Social Lead Event and processed in a background job so the platform
gets a fast 200.
"""

import hmac
import json

import frappe
from frappe.utils.password import get_decrypted_password
from werkzeug.wrappers import Response

from erp_social.integrations import config
from erp_social.social_integration.events import already_logged, enqueue_event, log_event
from erp_social.utils.meta_leads import extract_leadgen_changes, extract_messages
from erp_social.utils.signatures import verify_meta_signature
from erp_social.utils.tiktok_leads import extract_leads

ACCOUNT = "Social Platform Account"


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def meta(**kwargs):
	if frappe.request.method == "GET":
		return _meta_verify_subscription()
	return _meta_receive()


@frappe.whitelist(allow_guest=True, methods=["POST"])
def tiktok(**kwargs):
	token = frappe.request.args.get("token") or ""
	expected = config.tiktok_webhook_token()
	if not token or not hmac.compare_digest(token, expected):
		return _text("invalid token", 403)

	payload = _parse_json(frappe.request.get_data() or b"")
	accounts = {acc.external_id: acc for acc in _enabled_accounts("TikTok")}
	accepted = 0
	for lead in extract_leads(payload):
		account = accounts.get(lead["advertiser_id"])
		if not account:
			continue
		accepted += 1
		if already_logged("tiktok_lead", lead["lead_id"]):
			continue
		event = log_event("TikTok", account.name, "tiktok_lead", lead["lead_id"], lead)
		enqueue_event(event.name, "tiktok_lead")
	return _text("EVENT_RECEIVED" if accepted else "IGNORED")


def _meta_verify_subscription():
	args = frappe.local.form_dict
	mode, token, challenge = args.get("hub.mode"), args.get("hub.verify_token"), args.get("hub.challenge")
	if mode == "subscribe" and token and challenge:
		candidates = [config.meta_app()["verify_token"]]
		candidates += [
			get_decrypted_password(ACCOUNT, acc.name, "verify_token", raise_exception=False)
			for acc in _enabled_accounts("Facebook")
		]
		if any(c and hmac.compare_digest(c, token) for c in candidates):
			return _text(challenge)
	return _text("verification failed", 403)


def _meta_receive():
	body = frappe.request.get_data() or b""
	header = frappe.get_request_header("X-Hub-Signature-256")
	payload = _parse_json(body)

	by_id = {}
	for acc in _enabled_accounts("Facebook"):
		by_id[acc.external_id] = acc
		if acc.instagram_account_id:
			by_id[acc.instagram_account_id] = acc

	verified = {}  # account name -> bool, so each secret is checked once per delivery

	def trusted(account_id):
		account = by_id.get(account_id)
		if not account:
			return None
		if account.name not in verified:
			verified[account.name] = verify_meta_signature(body, header, _app_secret(account))
		return account if verified[account.name] else None

	accepted = 0
	for change in extract_leadgen_changes(payload):
		if account := trusted(change["page_id"]):
			accepted += 1
			_log_once(account.platform, account.name, "leadgen", change["leadgen_id"], change["raw"])

	for message in extract_messages(payload):
		if account := trusted(message["account_id"]):
			accepted += 1
			_log_once(message["platform"], account.name, "message", message["mid"], message)

	if verified and not any(verified.values()):
		return _text("invalid signature", 403)
	# 200 even when nothing matched (e.g. a Page with no account here) so Meta doesn't retry forever.
	return _text("EVENT_RECEIVED" if accepted else "IGNORED")


def _log_once(platform, account_name, event_type, external_id, payload):
	if already_logged(event_type, external_id):
		return
	event = log_event(platform, account_name, event_type, external_id, payload)
	enqueue_event(event.name, event_type)


def _enabled_accounts(platform):
	return frappe.get_all(
		ACCOUNT,
		filters={"enabled": 1, "platform": platform},
		fields=["name", "platform", "external_id", "instagram_account_id"],
	)


def _app_secret(account) -> str:
	own = get_decrypted_password(ACCOUNT, account.name, "app_secret", raise_exception=False)
	return own or config.meta_app()["app_secret"]


def _parse_json(body):
	try:
		data = json.loads(body or b"{}")
	except ValueError:
		return {}
	return data if isinstance(data, dict) else {}


def _text(body, status=200):
	return Response(body, status=status, mimetype="text/plain")
