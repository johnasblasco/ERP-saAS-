"""Development helpers (used by scripts/setup-bench.sh)."""

import frappe

from saas_control.bench import runner


def register_existing_site(site_name: str, url: str, plan: str = "Developer"):
	"""Adopt a site that already exists on this bench as an Active tenant (no provisioning)."""
	if not frappe.db.exists("SaaS Plan", plan):
		frappe.get_doc(
			{"doctype": "SaaS Plan", "plan_name": plan, "price": 0, "currency": "USD", "is_public": 0}
		).insert()

	subdomain = site_name.split(".")[0]
	tenant_key = frappe.generate_hash(length=48)
	tenant = (
		frappe.get_doc("Tenant", subdomain)
		if frappe.db.exists("Tenant", subdomain)
		else frappe.new_doc("Tenant")
	)
	tenant.update(
		{
			"subdomain": subdomain,
			"site_name": site_name,
			"company_name": subdomain.title(),
			"admin_name": "Administrator",
			"admin_email": "admin@example.com",
			"plan": plan,
			"status": "Active",
			"tenant_key": tenant_key,
			"provisioned_on": frappe.utils.now_datetime(),
		}
	)
	tenant.save()
	tenant.db_set("site_url", url.rstrip("/"))

	bench = runner(secrets=[tenant_key])
	bench.run("--site", site_name, "set-config", "saas_control_url", frappe.utils.get_url())
	bench.run("--site", site_name, "set-config", "saas_tenant_key", tenant_key)
	bench.run(
		"--site",
		site_name,
		"execute",
		"saas_tenant.setup.set_subscription",
		"--kwargs",
		frappe.as_json({"plan_name": plan, "status": "Active"}),
	)
	frappe.db.commit()
	return tenant.name
