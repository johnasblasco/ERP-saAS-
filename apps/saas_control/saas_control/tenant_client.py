"""Calls from the control plane to a tenant site's saas_tenant API (Bearer tenant key)."""

import frappe
import requests

TENANT_STATES = ("Trial", "Active", "Past Due", "Suspended")


class TenantUnreachable(Exception):
	pass


def _call(tenant, method, payload=None, http="POST"):
	key = tenant.get_password("tenant_key", raise_exception=False)
	if not key:
		raise TenantUnreachable(f"{tenant.name} has no tenant key")
	failure = None
	try:
		response = requests.request(
			http,
			f"{tenant.site_url}/api/method/saas_tenant.api.{method}",
			json=payload,
			headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
			timeout=20,
		)
	except requests.RequestException as e:
		failure = type(e).__name__
	if failure:
		raise TenantUnreachable(f"{tenant.site_url} unreachable ({failure})")
	if not response.ok:
		raise TenantUnreachable(f"{tenant.site_url} answered {response.status_code}: {response.text[:300]}")
	return (response.json() or {}).get("message")


def subscription_payload(tenant) -> dict:
	plan = frappe.get_cached_doc("SaaS Plan", tenant.plan)
	return {
		"plan_name": plan.plan_name,
		"status": tenant.status if tenant.status in TENANT_STATES else "Suspended",
		"max_users": plan.max_users or 0,
		"trial_ends_on": str(tenant.trial_ends_on) if tenant.trial_ends_on else None,
		"support_email": frappe.db.get_single_value("SaaS Settings", "support_email"),
	}


def push_state(tenant):
	return _call(tenant, "update_subscription", subscription_payload(tenant))


def fetch_usage(tenant) -> dict:
	return _call(tenant, "usage", http="GET") or {}
