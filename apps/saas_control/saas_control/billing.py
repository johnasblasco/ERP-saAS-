"""Bill tenants with ERPNext's own Subscriptions (the control site runs ERPNext too).

Each SaaS Plan maps to an ERPNext Subscription Plan; each tenant gets a Customer and a Subscription.
ERPNext's scheduler then raises the Sales Invoices, and `lifecycle.sync_billing_status` mirrors the
Subscription status (Grace Period, Unpaid, ...) onto the tenant.
"""

import frappe
from frappe import _

BILLING_ITEM = "SaaS Subscription"


def billing_enabled() -> bool:
	return bool(frappe.db.get_single_value("SaaS Settings", "billing_company"))


def ensure_billing_item() -> str:
	item = frappe.db.get_single_value("SaaS Settings", "billing_item")
	if item:
		return item
	if not frappe.db.exists("Item", BILLING_ITEM):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": BILLING_ITEM,
				"item_name": BILLING_ITEM,
				"item_group": _leaf_item_group(),
				"stock_uom": "Nos"
				if frappe.db.exists("UOM", "Nos")
				else frappe.db.get_value("UOM", {}, "name"),
				"is_stock_item": 0,
				"include_item_in_manufacturing": 0,
				"description": _("Subscription to the hosted ERP workspace"),
			}
		).insert(ignore_permissions=True)
	frappe.db.set_single_value("SaaS Settings", "billing_item", BILLING_ITEM)
	return BILLING_ITEM


def _leaf_item_group() -> str:
	for name in ("Services", "Products"):
		if frappe.db.exists("Item Group", name):
			return name
	return frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"


def sync_subscription_plan(plan) -> str | None:
	"""Create/update the ERPNext Subscription Plan behind a SaaS Plan. Free plans have none."""
	if not billing_enabled() or not plan.price:
		return None
	values = {
		"currency": plan.currency,
		"item": ensure_billing_item(),
		"price_determination": "Fixed Rate",
		"cost": plan.price,
		"billing_interval": plan.billing_interval or "Month",
		"billing_interval_count": 1,
	}
	if plan.subscription_plan and frappe.db.exists("Subscription Plan", plan.subscription_plan):
		doc = frappe.get_doc("Subscription Plan", plan.subscription_plan)
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{"doctype": "Subscription Plan", "plan_name": f"SaaS {plan.plan_name}", **values}
		)
		doc.insert(ignore_permissions=True)
	return doc.name


def ensure_customer(tenant) -> str:
	if tenant.customer and frappe.db.exists("Customer", tenant.customer):
		return tenant.customer
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": tenant.company_name,
			"customer_type": "Company",
		}
	).insert(ignore_permissions=True)
	contact = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": tenant.admin_name,
			"email_ids": [{"email_id": tenant.admin_email, "is_primary": 1}],
			"links": [{"link_doctype": "Customer", "link_name": customer.name}],
		}
	).insert(ignore_permissions=True)
	customer.db_set("customer_primary_contact", contact.name)
	return customer.name


def start_billing(tenant):
	"""Customer + Subscription for a freshly provisioned tenant (no-op for free plans)."""
	plan = frappe.get_doc("SaaS Plan", tenant.plan)
	subscription_plan = plan.subscription_plan or sync_subscription_plan(plan)
	if not subscription_plan:
		return None
	if plan.subscription_plan != subscription_plan:
		plan.db_set("subscription_plan", subscription_plan)

	settings = frappe.get_single("SaaS Settings")
	customer = ensure_customer(tenant)
	subscription = frappe.get_doc(
		{
			"doctype": "Subscription",
			"party_type": "Customer",
			"party": customer,
			"company": settings.billing_company,
			# During the trial ERPNext reports "Trialing" and raises no invoice.
			"start_date": frappe.utils.nowdate(),
			"trial_period_start": frappe.utils.nowdate() if tenant.trial_ends_on else None,
			"trial_period_end": tenant.trial_ends_on,
			"days_until_due": settings.days_until_due or 0,
			"generate_invoice_at": "Beginning of the current subscription period",
			"submit_invoice": 1,
			"plans": [{"plan": subscription_plan, "qty": 1}],
		}
	).insert(ignore_permissions=True)
	tenant.db_set({"customer": customer, "subscription": subscription.name})
	return subscription.name


def change_plan(tenant):
	"""Switch the tenant's Subscription to its current plan from the next invoice on."""
	if not tenant.subscription:
		return start_billing(tenant) if tenant.provisioned_on else None
	plan = frappe.get_doc("SaaS Plan", tenant.plan)
	subscription = frappe.get_doc("Subscription", tenant.subscription)
	if not plan.price:
		subscription.cancel_subscription()
		tenant.db_set("subscription", None)
		return None
	subscription_plan = plan.subscription_plan or sync_subscription_plan(plan)
	subscription.plans = []
	subscription.append("plans", {"plan": subscription_plan, "qty": 1})
	subscription.save(ignore_permissions=True)
	return subscription.name


def stop_billing(tenant):
	if (
		tenant.subscription
		and frappe.db.get_value("Subscription", tenant.subscription, "status") != "Cancelled"
	):
		frappe.get_doc("Subscription", tenant.subscription).cancel_subscription()
