"""Run by the control plane on a tenant site through `bench --site <site> execute ...`."""

import frappe

from saas_tenant.api import STATUSES


def set_subscription(plan_name, status, max_users=0, trial_ends_on=None, support_email=None):
	if status not in STATUSES:
		raise ValueError(f"Unknown status {status!r}")
	for field, value in {
		"plan_name": plan_name,
		"status": status,
		"max_users": int(max_users or 0),
		"trial_ends_on": trial_ends_on or None,
		"support_email": support_email,
		"updated_on": frappe.utils.now_datetime(),
	}.items():
		frappe.db.set_single_value("SaaS Subscription", field, value)
	frappe.local.cache.pop("saas_subscription", None)
	frappe.db.commit()


def initialize(
	owner_email, owner_name, plan_name, status, max_users=0, trial_ends_on=None, support_email=None
):
	"""Record the plan and create the customer's first user. Idempotent.

	Returns {"setup_link": ...}: a link for the owner to set their password. The control plane emails
	it, because a brand-new tenant site has no outgoing email account yet.
	"""
	set_subscription(plan_name, status, max_users, trial_ends_on, support_email)

	if frappe.db.exists("User", owner_email):
		user = frappe.get_doc("User", owner_email)
	else:
		first, _sep, last = (owner_name or "").partition(" ")
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": owner_email,
				"first_name": first or owner_email,
				"last_name": last,
				"send_welcome_email": 0,
				"roles": [{"role": "System Manager"}],
			}
		)
		user.flags.ignore_permissions = True
		user.insert()

	link = user._reset_password(send_email=False)
	frappe.db.commit()
	return {"setup_link": link}
