"""Authenticate calls from the SaaS control plane (Bearer <saas_tenant_key> from site_config)."""

import hmac

import frappe
from frappe import _


def require_control_plane():
	expected = frappe.conf.get("saas_tenant_key")
	header = frappe.get_request_header("Authorization") or ""
	scheme, _sep, token = header.partition(" ")
	if not expected or scheme.lower() != "bearer" or not hmac.compare_digest(token.strip(), expected):
		raise frappe.AuthenticationError(_("Invalid tenant key"))
