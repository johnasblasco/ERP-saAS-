import frappe
from frappe import _
from frappe.model.document import Document

from erp_social.social_integration.events import enqueue_event


class SocialLeadEvent(Document):
	@frappe.whitelist()
	def retry(self):
		self.check_permission("write")
		if self.status != "Failed":
			frappe.throw(_("Only failed events can be retried."))
		self.db_set({"status": "Received", "error": None})
		enqueue_event(self.name, self.event_type)
