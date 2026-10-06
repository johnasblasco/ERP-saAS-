import frappe
from frappe import _
from frappe.model.document import Document


class SocialPlatformAccount(Document):
	def validate(self):
		self.external_id = (self.external_id or "").strip()
		self.validate_unique_external_id()

	def validate_unique_external_id(self):
		# Webhook deliveries are routed by Page / Advertiser ID, so it must map to one enabled account.
		if not self.enabled:
			return
		duplicate = frappe.db.exists(
			"Social Platform Account",
			{"external_id": self.external_id, "enabled": 1, "name": ("!=", self.name)},
		)
		if duplicate:
			frappe.throw(
				_("Enabled account {0} already uses ID {1}.").format(
					frappe.bold(duplicate), frappe.bold(self.external_id)
				),
				title=_("Duplicate Page / Advertiser ID"),
			)
