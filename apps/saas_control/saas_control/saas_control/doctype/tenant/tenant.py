import frappe
from frappe import _
from frappe.model.document import Document

from saas_control.utils import normalize_subdomain, site_url, subdomain_error

LIVE = ("Trial", "Active", "Past Due", "Suspended")


class Tenant(Document):
	def autoname(self):
		self.subdomain = normalize_subdomain(self.subdomain)
		self.name = self.subdomain

	def validate(self):
		settings = frappe.get_cached_doc("SaaS Settings")
		if self.is_new():
			reserved = [r.strip() for r in (settings.reserved_subdomains or "").splitlines() if r.strip()]
			if error := subdomain_error(normalize_subdomain(self.subdomain), reserved):
				frappe.throw(_(error), title=_("Invalid subdomain"))
		elif self.has_value_changed("subdomain"):
			frappe.throw(_("A tenant's subdomain can't change once created."))

		self.site_name = self.site_name or f"{self.subdomain}.{settings.root_domain}"
		self.site_url = site_url(self.site_name, settings.url_scheme or "https", settings.public_port)
		self.admin_email = (self.admin_email or "").strip().lower()

	def on_update(self):
		if not self.is_new() and self.has_value_changed("plan") and self.status in LIVE:
			frappe.enqueue(
				"saas_control.saas_control.doctype.tenant.tenant.apply_plan_change",
				tenant_name=self.name,
				enqueue_after_commit=True,
			)

	def _require(self, *statuses):
		self.check_permission("write")
		if self.status not in statuses:
			frappe.throw(_("Not possible while the tenant is {0}.").format(_(self.status)))

	@frappe.whitelist()
	def provision(self):
		self._require("Pending Verification", "Failed", "Provisioning")
		from saas_control.provisioning import enqueue_provision

		enqueue_provision(self.name)

	@frappe.whitelist()
	def send_setup_link(self):
		self._require(*LIVE)
		frappe.enqueue(
			"saas_control.provisioning.resend_setup_link", tenant_name=self.name, enqueue_after_commit=True
		)

	@frappe.whitelist()
	def suspend(self):
		self._require("Trial", "Active", "Past Due")
		from saas_control.lifecycle import suspend

		suspend(self, "Manual")

	@frappe.whitelist()
	def resume(self):
		self._require("Suspended")
		from saas_control.lifecycle import resume

		resume(self)

	@frappe.whitelist()
	def sync_now(self):
		self._require(*LIVE)
		from saas_control.lifecycle import sync_tenant_usage

		sync_tenant_usage(self.name)

	@frappe.whitelist()
	def archive(self, confirm_subdomain: str):
		self._require(*LIVE, "Failed")
		if confirm_subdomain != self.subdomain:
			frappe.throw(_("Type the subdomain to confirm."))
		frappe.enqueue(
			"saas_control.lifecycle.archive_tenant",
			tenant_name=self.name,
			queue="long",
			timeout=3600,
			enqueue_after_commit=True,
		)


def apply_plan_change(tenant_name: str):
	from saas_control.billing import change_plan
	from saas_control.lifecycle import push_state_quietly

	tenant = frappe.get_doc("Tenant", tenant_name)
	change_plan(tenant)
	push_state_quietly(tenant)
