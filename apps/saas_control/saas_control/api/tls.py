"""On-demand TLS: the reverse proxy (Caddy) asks before issuing a certificate for a hostname.

	GET /api/method/saas_control.api.tls.allowed?domain=acme.example.com  ->  200 or 404

Only the control site itself and live tenant sites get certificates, so nobody can make the
proxy request certificates for arbitrary names pointed at it.
"""

import frappe
from werkzeug.wrappers import Response

SERVED = ("Trial", "Active", "Past Due", "Suspended")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def allowed(domain: str | None = None):
	domain = (domain or "").strip().lower().rstrip(".")
	control_host = frappe.utils.get_url().split("://", 1)[-1].split(":", 1)[0].lower()
	ok = bool(domain) and (
		domain in (control_host, frappe.local.site)
		or frappe.db.exists("Tenant", {"site_name": domain, "status": ("in", SERVED)})
	)
	return Response("ok" if ok else "unknown domain", status=200 if ok else 404, mimetype="text/plain")
