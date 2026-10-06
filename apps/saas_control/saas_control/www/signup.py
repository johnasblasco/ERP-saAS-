import frappe
from frappe.utils import fmt_money

no_cache = 1


def get_context(context):
	settings = frappe.get_cached_doc("SaaS Settings")
	website = frappe.get_cached_doc("Website Settings")
	default_plan = settings.default_plan

	plans = []
	for plan in frappe.get_all(
		"SaaS Plan",
		filters={"is_public": 1},
		fields=[
			"name",
			"plan_name",
			"price",
			"currency",
			"billing_interval",
			"max_users",
			"tagline",
			"features",
		],
		order_by="sort_order asc, price asc",
	):
		plans.append(
			{
				"name": plan.name,
				"label": plan.plan_name,
				"price": fmt_money(plan.price, currency=plan.currency, precision=0) if plan.price else None,
				"interval": "mo" if plan.billing_interval == "Month" else "yr",
				"users": plan.max_users or None,
				"tagline": plan.tagline,
				"features": [f.strip() for f in (plan.features or "").splitlines() if f.strip()],
				"default": plan.name == default_plan,
			}
		)
	if plans and not any(p["default"] for p in plans):
		plans[0]["default"] = True

	context.update(
		{
			"title": "Create your workspace",
			"brand": website.app_name or frappe.get_system_settings("app_name") or "ERP",
			"root_domain": settings.root_domain or "example.com",
			"trial_days": settings.trial_days or 0,
			"allow_signups": settings.allow_signups,
			"verify_email": settings.require_email_verification,
			"plans": plans,
			"csrf_token": frappe.sessions.get_csrf_token(),
			"no_header": 1,
		}
	)
	return context
