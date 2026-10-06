"""Social Lead Event lifecycle: log -> enqueue -> process (with failure capture and retry)."""

import json

import frappe

EVENT = "Social Lead Event"
SAVEPOINT = "erp_social_event"

# event_type -> background job that processes it
HANDLERS = {
	"leadgen": "erp_social.social_integration.lead_sync.process_meta_lead_event",
	"tiktok_lead": "erp_social.social_integration.lead_sync.process_tiktok_lead_event",
	"message": "erp_social.social_integration.messaging.process_message_event",
}


def log_event(platform, account, event_type, external_id, payload):
	return frappe.get_doc(
		{
			"doctype": EVENT,
			"platform": platform,
			"account": account,
			"event_type": event_type,
			"external_id": external_id,
			"status": "Received",
			"payload": json.dumps(payload, indent=1, default=str),
		}
	).insert(ignore_permissions=True)


def already_logged(event_type, external_id) -> bool:
	"""Platforms retry deliveries; one live event per external ID is enough."""
	return bool(
		frappe.db.exists(
			EVENT, {"event_type": event_type, "external_id": external_id, "status": ("!=", "Failed")}
		)
	)


def enqueue_event(event_name, event_type):
	frappe.enqueue(
		HANDLERS[event_type],
		event_name=event_name,
		enqueue_after_commit=True,
		deduplicate=True,
		job_id=f"erp_social::{event_type}::{event_name}",
	)


def run_event(event_name, handler):
	"""Run `handler(event) -> dict of fields to set` for a Received event.

	Jobs enqueued from webhooks run as Guest; documents should be created by a real system user.
	On failure only the handler's writes are rolled back (savepoint), never the event itself.
	"""
	frappe.set_user("Administrator")
	event = frappe.get_doc(EVENT, event_name)
	if event.status != "Received":
		return

	frappe.db.savepoint(SAVEPOINT)
	try:
		result = handler(event) or {}
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		event.db_set({"status": "Failed", "error": frappe.get_traceback()})
		frappe.log_error(
			title=f"Social event {event_name} failed", reference_doctype=EVENT, reference_name=event_name
		)
		return

	event.db_set({"status": result.pop("status", "Processed"), "error": None, **result})


def payload_of(event) -> dict:
	try:
		data = json.loads(event.payload or "{}")
	except ValueError:
		return {}
	return data if isinstance(data, dict) else {}
