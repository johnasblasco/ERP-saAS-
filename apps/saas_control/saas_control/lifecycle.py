"""Tenant state changes after provisioning: billing status, suspension, usage, archiving."""

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, nowdate

from saas_control.bench import BenchCommandError, runner
from saas_control.tenant_client import TenantUnreachable, fetch_usage, push_state
from saas_control.utils import SUBSCRIPTION_STATUS_MAP

TENANT = "Tenant"
LIVE = ("Trial", "Active", "Past Due", "Suspended")


def set_status(tenant, status, reason=None):
	"""Change a live tenant's status and tell the tenant site. Returns True when it changed."""
	if tenant.status == status:
		return False
	tenant.db_set({"status": status, "suspension_reason": reason if status == "Suspended" else None})
	push_state_quietly(tenant)
	return True


def push_state_quietly(tenant):
	try:
		push_state(tenant)
	except TenantUnreachable as e:
		# The daily sync pushes again, so a tenant that's briefly down catches up.
		tenant.db_set("error", str(e))


def suspend(tenant, reason="Manual"):
	set_status(tenant, "Suspended", reason)


def resume(tenant):
	status = _billing_status(tenant) or (
		"Trial" if tenant.trial_ends_on and getdate(tenant.trial_ends_on) >= getdate() else "Active"
	)
	if status == "Suspended":
		frappe.throw(_("The tenant's subscription is unpaid or cancelled. Settle it in ERPNext first."))
	set_status(tenant, status)


def _billing_status(tenant) -> str | None:
	if not tenant.subscription:
		return None
	return SUBSCRIPTION_STATUS_MAP.get(frappe.db.get_value("Subscription", tenant.subscription, "status"))


def sync_billing_status():
	"""Daily: mirror ERPNext Subscription status and trial expiry onto tenants."""
	for name in frappe.get_all(TENANT, filters={"status": ("in", LIVE)}, pluck="name"):
		tenant = frappe.get_doc(TENANT, name)
		if tenant.status == "Suspended" and tenant.suspension_reason == "Manual":
			continue  # an operator suspended it; only an operator resumes it

		status = _billing_status(tenant)
		if status is None:
			# No paid subscription: free plan, or billing not configured.
			trial_over = tenant.trial_ends_on and getdate(tenant.trial_ends_on) < getdate(nowdate())
			paid_plan = frappe.db.get_value("SaaS Plan", tenant.plan, "price")
			status = "Suspended" if trial_over and paid_plan else "Active" if trial_over else tenant.status
		set_status(tenant, status, "Billing")
	frappe.db.commit()


def sync_usage():
	"""Daily: pull usage numbers from each live tenant (and re-push state so it never drifts)."""
	for name in frappe.get_all(TENANT, filters={"status": ("in", LIVE)}, pluck="name"):
		frappe.enqueue(
			sync_tenant_usage, tenant_name=name, job_id=f"saas_control::usage::{name}", deduplicate=True
		)


def sync_tenant_usage(tenant_name: str):
	tenant = frappe.get_doc(TENANT, tenant_name)
	try:
		push_state(tenant)
		usage = fetch_usage(tenant)
	except TenantUnreachable as e:
		tenant.db_set("error", str(e))
		return
	tenant.db_set(
		{
			"active_users": usage.get("active_users") or 0,
			"db_size_mb": usage.get("db_size_mb") or 0,
			"last_login": usage.get("last_login") or None,
			"last_usage_sync": now_datetime(),
			"error": None,
		}
	)


def archive_tenant(tenant_name: str):
	"""Back up and drop the site, stop billing and release its social routes."""
	frappe.set_user("Administrator")
	tenant = frappe.get_doc(TENANT, tenant_name)
	bench = runner()
	try:
		if bench.site_exists(tenant.site_name):
			bench.run("--site", tenant.site_name, "backup", "--with-files")
			bench.run("drop-site", tenant.site_name, "--force", "--no-backup")
	except BenchCommandError as e:
		tenant.db_set({"error": str(e), "provisioning_log": bench.text_log()})
		frappe.db.commit()
		return

	from saas_control.billing import stop_billing

	stop_billing(tenant)
	frappe.db.delete("Tenant Social Route", {"tenant": tenant.name})
	tenant.db_set({"status": "Archived", "error": None, "provisioning_log": bench.text_log()})
	frappe.db.commit()


def daily():
	sync_billing_status()
	sync_usage()
