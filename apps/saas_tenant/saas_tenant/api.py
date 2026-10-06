"""Endpoints the SaaS control plane calls on each tenant site (Bearer tenant key)."""

import frappe
from frappe.utils import now_datetime

from saas_tenant.auth import require_control_plane
from saas_tenant.limits import active_system_users

STATUSES = ("Trial", "Active", "Past Due", "Suspended")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def update_subscription(plan_name=None, status=None, max_users=0, trial_ends_on=None, support_email=None):
	require_control_plane()
	if status not in STATUSES:
		frappe.throw(f"Unknown status {status!r}")
	values = {
		"plan_name": plan_name,
		"status": status,
		"max_users": int(max_users or 0),
		"trial_ends_on": trial_ends_on or None,
		"support_email": support_email,
		"updated_on": now_datetime(),
	}
	for field, value in values.items():
		frappe.db.set_single_value("SaaS Subscription", field, value)
	frappe.local.cache.pop("saas_subscription", None)
	return {"ok": True}


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def usage():
	require_control_plane()
	db_size = frappe.db.sql(
		"select coalesce(sum(data_length + index_length), 0) from information_schema.tables where table_schema = %s",
		frappe.conf.db_name,
	)[0][0]
	last_login = frappe.get_all(
		"User",
		filters={"name": ("not in", ["Administrator", "Guest"]), "last_login": ("is", "set")},
		pluck="last_login",
		order_by="last_login desc",
		limit=1,
	)
	return {
		"active_users": active_system_users(),
		"companies": frappe.db.count("Company") if frappe.db.table_exists("Company") else 0,
		"db_size_mb": round(float(db_size) / 1024 / 1024, 2),
		"last_login": str(last_login[0]) if last_login else "",
		"setup_complete": bool(frappe.is_setup_complete()),
	}
