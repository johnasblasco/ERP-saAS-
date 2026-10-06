"""Turn logged social lead events into ERPNext Leads (runs in background jobs)."""

import frappe
from frappe import _

from erp_social.integrations.config import meta_client
from erp_social.integrations.meta_api import MetaAPIError
from erp_social.social_integration.events import payload_of, run_event
from erp_social.utils.meta_leads import map_field_data
from erp_social.utils.tiktok_leads import map_lead


class GraphAPIError(frappe.ValidationError):
	pass


def process_meta_lead_event(event_name: str):
	run_event(event_name, _handle_meta_lead)


def process_tiktok_lead_event(event_name: str):
	run_event(event_name, _handle_tiktok_lead)


def _handle_meta_lead(event):
	account = frappe.get_doc("Social Platform Account", event.account)
	lead_data = fetch_meta_lead(account, event.external_id)
	lead = upsert_lead(account, map_field_data(lead_data.get("field_data")))
	return {"lead": lead.name}


def _handle_tiktok_lead(event):
	# TikTok delivers the form answers in the webhook itself; no API round trip needed.
	account = frappe.get_doc("Social Platform Account", event.account)
	lead = upsert_lead(account, map_lead(payload_of(event)))
	return {"lead": lead.name}


def fetch_meta_lead(account, leadgen_id: str) -> dict:
	page_token = account.get_password("access_token", raise_exception=False)
	if not page_token:
		frappe.throw(_("Account {0} has no Access Token.").format(account.name))
	try:
		return meta_client(account).get_lead(leadgen_id, page_token)
	except MetaAPIError as e:
		# MetaAPIError messages never contain tokens, so they're safe to store on the event.
		frappe.throw(str(e), exc=GraphAPIError)


def upsert_lead(account, fields: dict, notes: str | None = None):
	"""Create a Lead, or return the existing one when the email is already known."""
	if not (fields.get("first_name") or fields.get("company_name") or fields.get("email_id")):
		frappe.throw(_("Lead form answers contain no name, company or email."))

	if fields.get("email_id"):
		existing = frappe.db.get_value("Lead", {"email_id": fields["email_id"]})
		if existing:
			return frappe.get_doc("Lead", existing)

	lead = frappe.new_doc("Lead")
	lead.update(fields)
	lead.lead_owner = account.lead_owner or frappe.db.get_single_value(
		"Social Integration Settings", "default_lead_owner"
	)
	if account.utm_source:
		lead.utm_source = account.utm_source
	if notes:
		lead.append("notes", {"note": notes, "added_by": "Administrator", "added_on": frappe.utils.now()})
	return lead.insert(ignore_permissions=True)
