import re

import frappe
from frappe import _
from frappe.model.document import Document


class SocialIntegrationSettings(Document):
	def validate(self):
		if self.meta_graph_api_version and not re.fullmatch(
			r"v\d+\.\d+", self.meta_graph_api_version.strip()
		):
			frappe.throw(_("Graph API Version looks like v26.0"))
		if self.default_country_code:
			self.default_country_code = re.sub(r"\D", "", self.default_country_code)
