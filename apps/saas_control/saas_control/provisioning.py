"""Create a tenant site on this bench: new-site, install apps, register with the control plane."""

import json

import frappe
from frappe import _
from frappe.utils import add_days, get_url, now_datetime, nowdate

from saas_control.bench import BenchCommandError, runner
from saas_control.utils import parse_execute_output

TENANT = "Tenant"


def enqueue_provision(tenant_name: str):
	frappe.db.set_value(TENANT, tenant_name, {"status": "Queued", "error": None})
	frappe.enqueue(
		provision_tenant,
		tenant_name=tenant_name,
		queue="long",
		timeout=3600,
		enqueue_after_commit=True,
		deduplicate=True,
		job_id=f"saas_control::provision::{tenant_name}",
	)


def provision_tenant(tenant_name: str):
	frappe.set_user("Administrator")
	tenant = frappe.get_doc(TENANT, tenant_name)
	# "Provisioning" is allowed so a run killed mid-way (worker restart) can be retried.
	if tenant.status not in ("Queued", "Failed", "Pending Verification", "Provisioning"):
		return
	settings = frappe.get_single("SaaS Settings")

	tenant.db_set({"status": "Provisioning", "error": None, "provisioning_log": ""})
	frappe.db.commit()  # show progress to the signup page while the long steps run

	admin_password = frappe.generate_hash(length=24)
	tenant_key = tenant.get_password("tenant_key", raise_exception=False) or frappe.generate_hash(length=48)
	bench = runner(secrets=[admin_password, tenant_key])
	site = tenant.site_name

	try:
		if bench.site_exists(site):
			if tenant.provisioned_on:
				frappe.throw(_("Site {0} already exists and was provisioned before.").format(site))
			# Left over from an earlier failed attempt for this same (never-live) tenant.
			bench.run("drop-site", site, "--force", "--no-backup")

		new_site = ["new-site", site, "--admin-password", admin_password]
		if settings.db_user_host_scope:
			new_site += ["--mariadb-user-host-login-scope", settings.db_user_host_scope]
		bench.run(*new_site)

		apps = [a.strip() for a in (settings.apps_to_install or "").splitlines() if a.strip()]
		for app in apps:
			bench.run("--site", site, "install-app", app)

		for key, value in (
			("host_name", tenant.site_url),
			("saas_control_url", get_url()),
			("saas_tenant_key", tenant_key),
		):
			bench.run("--site", site, "set-config", key, value)

		tenant.status = "Trial" if tenant.trial_ends_on else "Active"
		setup_link = None
		if "saas_tenant" in apps:
			from saas_control.tenant_client import subscription_payload

			kwargs = {
				"owner_email": tenant.admin_email,
				"owner_name": tenant.admin_name,
				**subscription_payload(tenant),
			}
			output = bench.run(
				"--site", site, "execute", "saas_tenant.setup.initialize", "--kwargs", json.dumps(kwargs)
			)
			setup_link = (parse_execute_output(output) or {}).get("setup_link")
	except (BenchCommandError, frappe.ValidationError) as e:
		frappe.db.rollback()
		tenant.db_set({"status": "Failed", "error": str(e), "provisioning_log": bench.text_log()})
		frappe.log_error(
			title=f"Provisioning {tenant_name} failed", reference_doctype=TENANT, reference_name=tenant_name
		)
		frappe.db.commit()
		return

	status = tenant.status
	tenant.reload()
	# Saving through the document stores tenant_key encrypted (Password field).
	tenant.update(
		{
			"status": status,
			"tenant_key": tenant_key,
			"provisioned_on": now_datetime(),
			"provisioning_log": bench.text_log(),
		}
	)
	tenant.save(ignore_permissions=True)
	frappe.db.commit()  # the workspace is live; billing and email below are best-effort

	from saas_control.billing import start_billing

	try:
		start_billing(tenant)
		frappe.db.commit()
	except Exception:
		# The workspace works without an invoice schedule; billing can be fixed and retried later.
		frappe.db.rollback()
		frappe.log_error(
			title=f"Billing setup for {tenant_name} failed",
			reference_doctype=TENANT,
			reference_name=tenant_name,
		)

	send_ready_email(tenant, setup_link)
	frappe.db.commit()


def default_trial_end(trial_days: int | None):
	return add_days(nowdate(), int(trial_days)) if trial_days else None


def send_ready_email(tenant, setup_link) -> bool:
	sent = send_email(
		tenant,
		recipients=[tenant.admin_email],
		subject=_("Your {0} workspace is ready").format(tenant.company_name),
		template="saas_workspace_ready",
		args={
			"admin_name": tenant.admin_name,
			"company_name": tenant.company_name,
			"site_url": tenant.site_url,
			"setup_link": setup_link,
			"trial_ends_on": frappe.utils.formatdate(tenant.trial_ends_on) if tenant.trial_ends_on else None,
		},
	)
	return sent


def send_email(tenant, **kwargs) -> bool:
	"""Queue an email; without an outgoing Email Account record why on the tenant instead of failing."""
	try:
		frappe.sendmail(now=False, **kwargs)
	except frappe.OutgoingEmailError:
		tenant.db_set(
			"error",
			_("Email to {0} not sent: set up an outgoing Email Account, then use Send Setup Link.").format(
				", ".join(kwargs.get("recipients") or [])
			),
		)
		return False
	return True


def resend_setup_link(tenant_name: str):
	"""New set-password link for the owner (the previous one may have expired or never arrived)."""
	tenant = frappe.get_doc(TENANT, tenant_name)
	from saas_control.tenant_client import subscription_payload

	kwargs = {
		"owner_email": tenant.admin_email,
		"owner_name": tenant.admin_name,
		**subscription_payload(tenant),
	}
	bench = runner()
	output = bench.run(
		"--site", tenant.site_name, "execute", "saas_tenant.setup.initialize", "--kwargs", json.dumps(kwargs)
	)
	if send_ready_email(tenant, (parse_execute_output(output) or {}).get("setup_link")):
		tenant.db_set("error", None)
