"""Enforce the tenant's subscription state on every request."""

import frappe
from frappe import _

SUBSCRIPTION = "SaaS Subscription"

# Reachable even while suspended: control-plane calls, auth, and inbound social webhooks
# (leads keep flowing in so nothing is lost while the customer settles their bill).
ALLOWED_WHILE_SUSPENDED = (
	"/api/method/saas_tenant.api.",
	"/api/method/erp_social.api.webhooks.",
	"/api/method/login",
	"/api/method/logout",
	"/api/method/frappe.auth.get_logged_user",
	"/api/method/frappe.www.login.",
)


class SubscriptionSuspended(frappe.PermissionError):
	pass


def subscription() -> dict:
	"""Current plan state, cached per request. Empty dict when this site isn't a SaaS tenant."""
	if "saas_subscription" not in frappe.local.cache:
		state = {}
		if getattr(frappe.local, "db", None):
			state = {
				k: v
				for k, v in frappe.db.get_singles_dict(SUBSCRIPTION, cast=True).items()
				if k in ("plan_name", "status", "trial_ends_on", "max_users", "support_email")
			}
		frappe.local.cache["saas_subscription"] = state
	return frappe.local.cache["saas_subscription"]


def before_request():
	request = getattr(frappe.local, "request", None)
	if not request or not request.path.startswith("/api/"):
		return  # pages load; the desk shows a suspension notice from boot info
	if subscription().get("status") != "Suspended" or frappe.session.user == "Administrator":
		return
	if request.path.startswith(ALLOWED_WHILE_SUSPENDED):
		return
	raise SubscriptionSuspended(
		_("This workspace is suspended. Contact {0} to restore access.").format(
			subscription().get("support_email") or _("your provider")
		)
	)


def extend_bootinfo(bootinfo):
	state = subscription()
	if not state.get("status"):
		return
	bootinfo.saas_subscription = {**state, "trial_ends_on": str(state.get("trial_ends_on") or "")}
