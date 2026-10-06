import frappe
from frappe import _
from frappe.model.document import Document


class SocialLeadEvent(Document):
	@frappe.whitelist()
	def retry(self):
		self.check_permission("write")
		if self.status != "Failed":
			frappe.throw(_("Only failed events can be retried."))
		if self.platform not in ("Facebook", "Instagram"):
			frappe.throw(_("Automatic processing is not available for {0} yet.").format(self.platform))

		from erp_social.social_integration.lead_sync import process_meta_lead_event

		self.db_set({"status": "Received", "error": None})
		frappe.enqueue(
			process_meta_lead_event,
			event_name=self.name,
			enqueue_after_commit=True,
			deduplicate=True,
			job_id=f"erp_social::meta_lead::{self.name}",
		)
