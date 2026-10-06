"""Public signup: pick a plan and subdomain -> verify email -> workspace is provisioned."""

import hmac

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import validate_email_address
from frappe.utils.password import get_decrypted_password
from werkzeug.utils import redirect

from saas_control.provisioning import default_trial_end, enqueue_provision
from saas_control.utils import normalize_subdomain, subdomain_error

TENANT = "Tenant"
PUBLIC_STATUS = {
	"Pending Verification": "verify_email",
	"Queued": "provisioning",
	"Provisioning": "provisioning",
	"Trial": "ready",
	"Active": "ready",
	"Past Due": "ready",
	"Suspended": "unavailable",
	"Failed": "failed",
	"Archived": "unavailable",
}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def plans():
	return frappe.get_all(
		"SaaS Plan",
		filters={"is_public": 1},
		fields=["plan_name", "price", "currency", "billing_interval", "max_users", "tagline", "features"],
		order_by="sort_order asc, price asc",
	)


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=60, seconds=60)
def check_subdomain(subdomain: str):
	subdomain = normalize_subdomain(subdomain)
	error = _subdomain_problem(subdomain)
	return {"subdomain": subdomain, "available": not error, "message": error}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=60 * 60)
def create(company_name: str, full_name: str, email: str, subdomain: str, plan: str | None = None):
	settings = frappe.get_single("SaaS Settings")
	if not settings.allow_signups:
		frappe.throw(_("Signups are closed right now."))

	email = (email or "").strip().lower()
	if not validate_email_address(email):
		frappe.throw(_("Enter a valid email address."))
	company_name, full_name = (company_name or "").strip(), (full_name or "").strip()
	if not company_name or not full_name:
		frappe.throw(_("Enter your name and company."))
	subdomain = normalize_subdomain(subdomain)
	if error := _subdomain_problem(subdomain):
		frappe.throw(error)

	plan = plan or settings.default_plan
	if not plan or not frappe.db.get_value("SaaS Plan", {"name": plan, "is_public": 1}):
		frappe.throw(_("Choose a plan."))
	pending = frappe.db.count(TENANT, {"admin_email": email, "status": "Pending Verification"})
	if pending >= 3:
		frappe.throw(_("Check your inbox: we already sent you verification links."))

	token = frappe.generate_hash(length=40)
	tenant = frappe.get_doc(
		{
			"doctype": TENANT,
			"subdomain": subdomain,
			"company_name": company_name,
			"admin_name": full_name,
			"admin_email": email,
			"plan": plan,
			"trial_ends_on": default_trial_end(settings.trial_days),
			"status": "Pending Verification",
			"verification_token": token,
		}
	).insert(ignore_permissions=True)

	if settings.require_email_verification:
		send_verification_email(tenant, token)
		return {"workspace": tenant.name, "next": "verify_email"}
	enqueue_provision(tenant.name)
	return {"workspace": tenant.name, "next": "provisioning"}


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=30, seconds=60 * 60)
def verify(workspace: str, token: str):
	expected = (
		get_decrypted_password(TENANT, workspace, "verification_token", raise_exception=False)
		if frappe.db.exists(TENANT, workspace)
		else None
	)
	if not expected or not hmac.compare_digest(expected, token or ""):
		return redirect("/signup?error=invalid_link")
	if frappe.db.get_value(TENANT, workspace, "status") == "Pending Verification":
		enqueue_provision(workspace)
	return redirect(f"/signup?workspace={workspace}")


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=120, seconds=60)
def status(workspace: str):
	row = frappe.db.get_value(TENANT, workspace, ["status", "site_url"], as_dict=True)
	if not row:
		return {"state": "unknown"}
	state = PUBLIC_STATUS.get(row.status, "unavailable")
	return {"state": state, "url": row.site_url if state == "ready" else None}


def _subdomain_problem(subdomain: str) -> str | None:
	reserved = [
		r.strip()
		for r in (frappe.db.get_single_value("SaaS Settings", "reserved_subdomains") or "").splitlines()
	]
	if error := subdomain_error(subdomain, reserved):
		return _(error)
	if frappe.db.exists(TENANT, subdomain):
		return _("That address is taken.")
	return None


def send_verification_email(tenant, token):
	from urllib.parse import urlencode

	link = frappe.utils.get_url(
		"/api/method/saas_control.api.signup.verify?" + urlencode({"workspace": tenant.name, "token": token})
	)
	try:
		frappe.sendmail(
			recipients=[tenant.admin_email],
			subject=_("Confirm your email to create {0}").format(tenant.site_name),
			template="saas_verify_email",
			args={"admin_name": tenant.admin_name, "site_name": tenant.site_name, "link": link},
			now=False,
		)
	except frappe.OutgoingEmailError:
		# Raising rolls back the whole request, so no half-created tenant is left behind.
		frappe.log_error(title="Signup verification email could not be sent")
		frappe.throw(_("We can't send email right now, so signups are paused. Please try again later."))
