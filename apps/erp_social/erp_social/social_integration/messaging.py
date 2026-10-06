"""Messenger / Instagram DMs <-> ERPNext Lead conversations."""

from datetime import UTC, datetime

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.data import convert_utc_to_system_timezone

from erp_social.integrations.config import meta_client
from erp_social.integrations.meta_api import MetaAPIError
from erp_social.social_integration.events import payload_of, run_event


def process_message_event(event_name: str):
	run_event(event_name, _handle_message)


def _handle_message(event):
	message = payload_of(event)
	account = frappe.get_doc("Social Platform Account", event.account)
	contact = get_or_create_contact(account, message["platform"], message["sender_id"])

	if not contact.lead and frappe.db.get_single_value(
		"Social Integration Settings", "create_leads_from_messages"
	):
		contact.db_set("lead", _create_lead_for_contact(account, contact).name)

	sent_on = _timestamp(message.get("timestamp"))
	contact.db_set("last_message_on", sent_on)
	communication = make_communication(
		contact,
		content=_message_html(message),
		sent_or_received="Received",
		communication_date=sent_on,
		message_id=message.get("mid"),
	)
	return {"contact": contact.name, "lead": contact.lead, "communication": communication.name}


def get_or_create_contact(account, platform, external_user_id):
	name = frappe.db.get_value(
		"Social Contact", {"account": account.name, "external_user_id": external_user_id}
	)
	if name:
		return frappe.get_doc("Social Contact", name)

	profile = {}
	page_token = account.get_password("access_token", raise_exception=False)
	if page_token:
		try:
			profile = meta_client(account).get_profile(external_user_id, page_token, platform)
		except MetaAPIError:
			profile = {}  # Profile access needs extra permissions on some pages; a name is optional.

	full_name = (
		profile.get("name")
		or " ".join(p for p in (profile.get("first_name"), profile.get("last_name")) if p)
		or _("{0} user {1}").format(platform, external_user_id[-6:])
	)
	return frappe.get_doc(
		{
			"doctype": "Social Contact",
			"platform": platform,
			"account": account.name,
			"external_user_id": external_user_id,
			"full_name": full_name,
			"username": profile.get("username"),
		}
	).insert(ignore_permissions=True)


def _create_lead_for_contact(account, contact):
	from erp_social.social_integration.lead_sync import upsert_lead

	first, _sep, last = (contact.full_name or "").partition(" ")
	fields = {"first_name": first or contact.full_name}
	if last:
		fields["last_name"] = last
	return upsert_lead(account, fields, notes=_("Started a conversation on {0}.").format(contact.platform))


def make_communication(contact, content, sent_or_received, communication_date=None, message_id=None):
	return frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Chat",
			"sent_or_received": sent_or_received,
			"status": "Linked",
			"subject": _("{0} message").format(contact.platform),
			"content": content,
			"sender_full_name": contact.full_name if sent_or_received == "Received" else frappe.session.user,
			"communication_date": communication_date or now_datetime(),
			"message_id": message_id,
			"reference_doctype": "Lead" if contact.lead else "Social Contact",
			"reference_name": contact.lead or contact.name,
		}
	).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def send_reply(lead: str, message: str):
	"""Reply to the Lead's latest Messenger / Instagram conversation."""
	frappe.has_permission("Lead", "write", doc=lead, throw=True)
	message = (message or "").strip()
	if not message:
		frappe.throw(_("Write a message first."))

	contact_name = frappe.db.get_value(
		"Social Contact", {"lead": lead}, "name", order_by="last_message_on desc"
	)
	if not contact_name:
		frappe.throw(_("This Lead hasn't messaged you on Facebook or Instagram."))
	contact = frappe.get_doc("Social Contact", contact_name)
	account = frappe.get_doc("Social Platform Account", contact.account)

	page_token = account.get_password("access_token", raise_exception=False)
	if not page_token:
		frappe.throw(_("Account {0} has no Access Token.").format(account.name))
	try:
		result = meta_client(account).send_message(
			account.external_id, page_token, contact.external_user_id, message
		)
	except MetaAPIError as e:
		if e.code == 10:
			frappe.throw(_("Meta only allows replies within 24 hours of the customer's last message."))
		frappe.throw(str(e))

	communication = make_communication(
		contact,
		content=frappe.utils.escape_html(message),
		sent_or_received="Sent",
		message_id=result.get("message_id"),
	)
	return {"communication": communication.name}


def _message_html(message) -> str:
	parts = [frappe.utils.escape_html(message.get("text") or "")]
	for url in message.get("attachments") or []:
		safe = frappe.utils.escape_html(url)
		parts.append(f'<a href="{safe}" target="_blank" rel="noopener noreferrer">{_("Attachment")}</a>')
	return "<br>".join(p for p in parts if p) or _("(empty message)")


def _timestamp(ms):
	"""Meta sends epoch milliseconds (UTC); Datetime fields hold naive system-timezone values."""
	try:
		utc = datetime.fromtimestamp(int(ms) / 1000, tz=UTC)
	except TypeError, ValueError, OverflowError:
		return now_datetime()
	return convert_utc_to_system_timezone(utc).replace(tzinfo=None)
