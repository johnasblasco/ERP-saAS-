import frappe
from frappe import _
from frappe.model.document import Document


class SaaSPlan(Document):
	def validate(self):
		if (self.price or 0) < 0 or (self.max_users or 0) < 0:
			frappe.throw(_("Price and Max Users can't be negative."))

	def on_update(self):
		from saas_control.billing import sync_subscription_plan

		name = sync_subscription_plan(self)
		if name and name != self.subscription_plan:
			self.db_set("subscription_plan", name)
