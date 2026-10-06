"""Plan limits enforced inside the tenant site."""

import frappe
from frappe import _

from saas_tenant.guard import subscription

SYSTEM_ACCOUNTS = ("Administrator", "Guest")


def active_system_users(exclude: str | None = None) -> int:
	filters = {
		"enabled": 1,
		"user_type": "System User",
		"name": ("not in", [*SYSTEM_ACCOUNTS, exclude or ""]),
	}
	return frappe.db.count("User", filters)


def validate_user_limit(doc, method=None):
	max_users = int(subscription().get("max_users") or 0)
	if not max_users or doc.name in SYSTEM_ACCOUNTS or frappe.flags.in_install:
		return
	if not (doc.enabled and doc.user_type == "System User"):
		return
	before = doc.get_doc_before_save()
	if before and before.enabled and before.user_type == "System User":
		return  # already counted; editing an existing user never hits the limit
	if active_system_users(exclude=doc.name) >= max_users:
		frappe.throw(
			_("Your {0} plan includes {1} users. Disable a user or upgrade your plan.").format(
				subscription().get("plan_name") or "", max_users
			),
			title=_("User limit reached"),
		)
