"""Turn logged social lead events into ERPNext Leads (runs in background jobs)."""

import frappe
import requests
from frappe import _

from erp_social.utils.meta_leads import map_field_data
from erp_social.utils.signatures import meta_appsecret_proof

GRAPH_LEAD_URL = "https://graph.facebook.com/{version}/{leadgen_id}"
GRAPH_LEAD_FIELDS = "field_data,created_time,ad_id,form_id"
SAVEPOINT = "erp_social_lead_sync"


class GraphAPIError(frappe.ValidationError):
	pass


def process_meta_lead_event(event_name: str):
	# Jobs enqueued from the webhook run as Guest; Leads should be created by a real system user.
	frappe.set_user("Administrator")

	event = frappe.get_doc("Social Lead Event", event_name)
	if event.status != "Received":
		return

	# Roll back only a half-created Lead on failure, never the event itself.
	frappe.db.savepoint(SAVEPOINT)
	try:
		account = frappe.get_doc("Social Platform Account", event.account)
		lead_data = fetch_meta_lead(account, event.external_id)
		lead = upsert_lead(account, map_field_data(lead_data.get("field_data")))
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		event.db_set({"status": "Failed", "error": frappe.get_traceback()})
		frappe.log_error(
			title=f"Social lead {event_name} failed",
			reference_doctype="Social Lead Event",
			reference_name=event_name,
		)
		return

	event.db_set({"status": "Processed", "lead": lead.name, "error": None})


def fetch_meta_lead(account, leadgen_id: str) -> dict:
	access_token = account.get_password("access_token", raise_exception=False)
	if not access_token:
		frappe.throw(_("Account {0} has no Access Token.").format(account.name))

	response, network_error = None, None
	try:
		response = requests.get(
			GRAPH_LEAD_URL.format(version=account.graph_api_version or "v23.0", leadgen_id=leadgen_id),
			params={
				"access_token": access_token,
				"appsecret_proof": meta_appsecret_proof(access_token, account.get_password("app_secret")),
				"fields": GRAPH_LEAD_FIELDS,
			},
			timeout=20,
		)
	except requests.RequestException as e:
		network_error = type(e).__name__
	if network_error:
		# Raised outside the except block so the stored traceback doesn't chain the original
		# exception, whose message contains the full URL including access_token.
		frappe.throw(_("Could not reach the Graph API ({0}).").format(network_error), exc=GraphAPIError)
	if not response.ok:
		# Graph API errors carry the useful detail in the body, not the status line.
		frappe.throw(_("Graph API returned {0}: {1}").format(response.status_code, response.text[:500]))
	return response.json()


def upsert_lead(account, fields: dict):
	"""Create a Lead, or return the existing one when the email is already known."""
	if not (fields.get("first_name") or fields.get("company_name") or fields.get("email_id")):
		frappe.throw(_("Lead form answers contain no name, company or email."))

	if fields.get("email_id"):
		existing = frappe.db.get_value("Lead", {"email_id": fields["email_id"]})
		if existing:
			return frappe.get_doc("Lead", existing)

	lead = frappe.new_doc("Lead")
	lead.update(fields)
	if account.lead_owner:
		lead.lead_owner = account.lead_owner
	if account.utm_source:
		lead.utm_source = account.utm_source
	return lead.insert(ignore_permissions=True)
