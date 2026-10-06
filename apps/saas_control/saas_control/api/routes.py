"""Tenants register which Meta Page / Instagram IDs they own (see erp_social.social_integration.routes)."""

import hmac

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password

ROUTE = "Tenant Social Route"
INACTIVE = ("Archived", "Failed")
MAX_IDS = 1000


def authenticate_tenant():
	"""Tenant named by X-Tenant-Site, proven by its Bearer key. Raises AuthenticationError."""
	site = frappe.get_request_header("X-Tenant-Site") or ""
	scheme, _sep, key = (frappe.get_request_header("Authorization") or "").partition(" ")
	name = (
		frappe.db.get_value("Tenant", {"site_name": site, "status": ("not in", INACTIVE)}) if site else None
	)
	expected = name and get_decrypted_password("Tenant", name, "tenant_key", raise_exception=False)
	if not expected or scheme.lower() != "bearer" or not hmac.compare_digest(key.strip(), expected):
		raise frappe.AuthenticationError(_("Unknown tenant or wrong key"))
	return name


@frappe.whitelist(allow_guest=True, methods=["POST"])
def sync(platform: str = "Meta", external_ids=None):
	"""Replace this tenant's routes for `platform` with `external_ids`. IDs owned by another live
	tenant are refused (a Page can only deliver to one workspace)."""
	tenant = authenticate_tenant()
	if platform != "Meta":
		frappe.throw(_("Unsupported platform"))
	if isinstance(external_ids, str):
		external_ids = frappe.parse_json(external_ids)
	wanted = {str(i).strip() for i in external_ids or [] if str(i).strip()}
	if len(wanted) > MAX_IDS:
		frappe.throw(_("Too many IDs"))

	fields = ["name", "external_id", "tenant"]
	mine = frappe.get_all(ROUTE, filters={"platform": platform, "tenant": tenant}, fields=fields)
	for route in mine:
		if route.external_id not in wanted:
			frappe.delete_doc(ROUTE, route.name, ignore_permissions=True, force=True)

	conflicts = set()
	others = (
		frappe.get_all(
			ROUTE,
			filters={"platform": platform, "external_id": ("in", list(wanted)), "tenant": ("!=", tenant)},
			fields=fields,
		)
		if wanted
		else []
	)
	for route in others:
		if frappe.db.get_value("Tenant", route.tenant, "status") in INACTIVE:
			frappe.delete_doc(
				ROUTE, route.name, ignore_permissions=True, force=True
			)  # freed by an archived tenant
		else:
			conflicts.add(route.external_id)

	already = {r.external_id for r in mine}
	for external_id in sorted(wanted - already - conflicts):
		frappe.get_doc(
			{"doctype": ROUTE, "platform": platform, "external_id": external_id, "tenant": tenant}
		).insert(ignore_permissions=True)
	return {"registered": sorted(wanted - conflicts), "conflicts": sorted(conflicts)}
