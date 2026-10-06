import frappe
from frappe import _
from frappe.model.document import Document


class SocialAudience(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if before and before.account != self.account and self.audience_id:
			frappe.throw(
				_(
					"This audience already exists on the platform. Create a new Social Audience for another account."
				)
			)

	@frappe.whitelist()
	def sync_now(self):
		self.check_permission("write")
		from erp_social.social_integration.audiences import sync_audience

		frappe.enqueue(
			sync_audience,
			audience_name=self.name,
			queue="long",
			enqueue_after_commit=True,
			deduplicate=True,
			job_id=f"erp_social::audience::{self.name}",
		)
