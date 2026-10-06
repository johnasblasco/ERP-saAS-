from frappe.model.document import Document


class SaaSSettings(Document):
	def validate(self):
		self.root_domain = (self.root_domain or "").strip().lower().strip(".")
