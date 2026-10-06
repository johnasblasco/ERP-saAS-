import ast
import hashlib
import hmac
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate, set_request

from saas_control import lifecycle, provisioning
from saas_control.api import relay, router, routes, signup
from saas_control.bench import BenchCommandError

SECRET = "shared-meta-secret"


def settings(**values):
	doc = frappe.get_single("SaaS Settings")
	doc.update(
		{
			"root_domain": "example.test",
			"url_scheme": "https",
			"public_port": 0,
			"allow_signups": 1,
			"require_email_verification": 1,
			"trial_days": 14,
			"apps_to_install": "erpnext\nerp_social\nsaas_tenant",
			"reserved_subdomains": "www\nadmin",
			"billing_company": None,
			**values,
		}
	)
	doc.save(ignore_permissions=True)
	return doc


def plan(name="Test Starter", price=0, **values):
	if not frappe.db.exists("SaaS Plan", name):
		frappe.get_doc(
			{
				"doctype": "SaaS Plan",
				"plan_name": name,
				"price": price,
				"currency": "USD",
				"max_users": 5,
				"is_public": 1,
				**values,
			}
		).insert(ignore_permissions=True)
	return name


def tenant(subdomain="acme", status="Active", **values):
	if frappe.db.exists("Tenant", subdomain):
		frappe.delete_doc("Tenant", subdomain, force=True, ignore_permissions=True)
	doc = frappe.get_doc(
		{
			"doctype": "Tenant",
			"subdomain": subdomain,
			"company_name": subdomain.title(),
			"admin_name": "Owner Person",
			"admin_email": f"owner@{subdomain}.test",
			"plan": plan(),
			"status": status,
			"tenant_key": f"key-{subdomain}",
			**values,
		}
	).insert(ignore_permissions=True)
	return doc


@contextmanager
def capture_enqueue():
	jobs = []
	with patch("frappe.enqueue", lambda method, **kwargs: jobs.append((method, kwargs))):
		yield jobs


def location(response):
	return response.headers["Location"]


class ControlTestCase(IntegrationTestCase):
	def setUp(self):
		settings()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()


class TestTenantAndSignup(ControlTestCase):
	def test_tenant_site_name_and_url(self):
		doc = tenant("globex")
		self.assertEqual(
			(doc.site_name, doc.site_url), ("globex.example.test", "https://globex.example.test")
		)

	def test_reserved_and_invalid_subdomains_rejected(self):
		for bad in ("admin", "a", "bad_name"):
			with self.assertRaises(frappe.ValidationError):
				tenant(bad)

	def test_signup_verify_and_status(self):
		plan()
		with patch("frappe.sendmail") as sendmail:
			result = signup.create(
				"Initech", "Peter Gibbons", "Peter@Initech.test", "initech", "Test Starter"
			)
		self.assertEqual(result, {"workspace": "initech", "next": "verify_email"})
		doc = frappe.get_doc("Tenant", "initech")
		self.assertEqual(
			(doc.status, doc.admin_email, doc.site_name),
			("Pending Verification", "peter@initech.test", "initech.example.test"),
		)
		self.assertEqual(str(doc.trial_ends_on), add_days(nowdate(), 14))
		link = sendmail.call_args.kwargs["args"]["link"]
		token = parse_qs(urlparse(link).query)["token"][0]

		self.assertIn("error=invalid_link", location(signup.verify("initech", "wrong-token")))
		with capture_enqueue() as jobs:
			response = signup.verify("initech", token)
		self.assertEqual(location(response), "/signup?workspace=initech")
		self.assertEqual(frappe.db.get_value("Tenant", "initech", "status"), "Queued")
		self.assertTrue(jobs[0][0].__name__ == "provision_tenant")
		self.assertEqual(signup.status("initech"), {"state": "provisioning", "url": None})
		self.assertEqual(signup.status("nope"), {"state": "unknown"})

	def test_signup_rejects_taken_and_closed(self):
		tenant("taken")
		self.assertFalse(signup.check_subdomain("Taken")["available"])
		self.assertTrue(signup.check_subdomain("fresh-name")["available"])
		with self.assertRaises(frappe.ValidationError):
			signup.create("X", "Y Z", "y@z.test", "taken", plan())
		settings(allow_signups=0)
		with self.assertRaises(frappe.ValidationError):
			signup.create("X", "Y Z", "y@z.test", "another", plan())

	def test_plans_lists_only_public(self):
		plan()
		plan("Test Hidden", is_public=0)
		names = [p.plan_name for p in signup.plans()]
		self.assertIn("Test Starter", names)
		self.assertNotIn("Test Hidden", names)


class FakeRunner:
	def __init__(self, fail_on=None, existing=False):
		self.commands, self.fail_on, self.existing = [], fail_on, existing

	def run(self, *args, timeout=None):
		self.commands.append(args)
		if self.fail_on and self.fail_on in args:
			raise BenchCommandError(f"{self.fail_on} failed")
		if "execute" in args:
			return 'warning line\n{"setup_link": "https://acme.example.test/update-password?key=abc"}'
		return "ok"

	def site_exists(self, site):
		return self.existing

	def text_log(self):
		return "\n".join(" ".join(c) for c in self.commands)


class TestProvisioning(ControlTestCase):
	def test_provision_runs_commands_and_activates(self):
		doc = tenant("acme", status="Queued", trial_ends_on=add_days(nowdate(), 14))
		fake = FakeRunner()
		with (
			patch.object(provisioning, "runner", lambda secrets=None: fake),
			patch("frappe.sendmail") as sendmail,
			patch("frappe.db.commit"),
		):
			provisioning.provision_tenant(doc.name)

		doc.reload()
		self.assertEqual(doc.status, "Trial")
		self.assertTrue(doc.provisioned_on)
		self.assertEqual(fake.commands[0][:2], ("new-site", "acme.example.test"))
		self.assertIn(("--site", "acme.example.test", "install-app", "erp_social"), fake.commands)
		configs = {c[3]: c[4] for c in fake.commands if "set-config" in c}
		self.assertEqual(configs["host_name"], "https://acme.example.test")
		self.assertEqual(configs["saas_tenant_key"], doc.get_password("tenant_key"))
		initialize = next(c for c in fake.commands if "execute" in c)
		self.assertEqual(ast.literal_eval(initialize[-1])["owner_email"], "owner@acme.test")
		self.assertEqual(
			sendmail.call_args.kwargs["args"]["setup_link"],
			"https://acme.example.test/update-password?key=abc",
		)

	def test_failed_install_marks_failed_and_retry_drops_leftover_site(self):
		doc = tenant("acme", status="Queued")
		with (
			patch.object(provisioning, "runner", lambda secrets=None: FakeRunner(fail_on="install-app")),
			patch("frappe.db.commit"),
			patch("frappe.db.rollback"),
		):
			provisioning.provision_tenant(doc.name)
		doc.reload()
		self.assertEqual(doc.status, "Failed")
		self.assertIn("install-app failed", doc.error)

		fake = FakeRunner(existing=True)
		with (
			patch.object(provisioning, "runner", lambda secrets=None: fake),
			patch("frappe.sendmail"),
			patch("frappe.db.commit"),
		):
			provisioning.provision_tenant(doc.name)
		self.assertEqual(fake.commands[0], ("drop-site", "acme.example.test", "--force", "--no-backup"))
		self.assertEqual(frappe.db.get_value("Tenant", doc.name, "status"), "Active")

	def test_missing_email_account_keeps_tenant_live_and_records_why(self):
		doc = tenant("acme", status="Queued")
		no_email = patch("frappe.sendmail", side_effect=frappe.OutgoingEmailError("no account"))
		with (
			patch.object(provisioning, "runner", lambda secrets=None: FakeRunner()),
			no_email,
			patch("frappe.db.commit"),
		):
			provisioning.provision_tenant(doc.name)
		doc.reload()
		self.assertEqual(doc.status, "Active")
		self.assertIn("Send Setup Link", doc.error)

	def test_signup_without_email_account_fails_cleanly(self):
		plan()
		with (
			patch("frappe.sendmail", side_effect=frappe.OutgoingEmailError("no account")),
			patch("frappe.log_error"),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "signups are paused"):
				signup.create("Hooli", "Gavin B", "gavin@hooli.test", "hooli", "Test Starter")

	def test_never_drops_a_previously_live_site(self):
		doc = tenant("acme", status="Failed", provisioned_on=frappe.utils.now_datetime())
		fake = FakeRunner(existing=True)
		with (
			patch.object(provisioning, "runner", lambda secrets=None: fake),
			patch("frappe.db.commit"),
			patch("frappe.db.rollback"),
		):
			provisioning.provision_tenant(doc.name)
		self.assertEqual(fake.commands, [])
		self.assertEqual(frappe.db.get_value("Tenant", doc.name, "status"), "Failed")


class TestLifecycle(ControlTestCase):
	def test_trial_over_on_paid_plan_without_billing_suspends(self):
		paid = plan("Test Paid", price=29)
		doc = tenant("acme", status="Trial", plan=paid, trial_ends_on=add_days(nowdate(), -1))
		with patch.object(lifecycle, "push_state") as push, patch("frappe.db.commit"):
			lifecycle.sync_billing_status()
		doc.reload()
		self.assertEqual((doc.status, doc.suspension_reason), ("Suspended", "Billing"))
		push.assert_called_once()

	def test_free_plan_trial_becomes_active(self):
		doc = tenant("acme", status="Trial", trial_ends_on=add_days(nowdate(), -1))
		with patch.object(lifecycle, "push_state"), patch("frappe.db.commit"):
			lifecycle.sync_billing_status()
		self.assertEqual(frappe.db.get_value("Tenant", doc.name, "status"), "Active")

	def test_subscription_status_is_mirrored_and_manual_suspension_kept(self):
		doc = tenant("acme", status="Active")
		manual = tenant("manual", status="Suspended", suspension_reason="Manual")
		with (
			patch.object(lifecycle, "_billing_status", return_value="Past Due"),
			patch.object(lifecycle, "push_state"),
			patch("frappe.db.commit"),
		):
			lifecycle.sync_billing_status()
		self.assertEqual(frappe.db.get_value("Tenant", doc.name, "status"), "Past Due")
		self.assertEqual(frappe.db.get_value("Tenant", manual.name, "status"), "Suspended")

	def test_unreachable_tenant_records_error(self):
		doc = tenant("acme", status="Active")
		doc.site_url = "http://127.0.0.1:9"  # nothing listens on the discard port
		doc.db_set("site_url", doc.site_url)
		lifecycle.suspend(doc, "Manual")
		doc.reload()
		self.assertEqual(doc.status, "Suspended")
		self.assertIn("unreachable", doc.error)


class TestBilling(ControlTestCase):
	"""Runs against real ERPNext Subscriptions; needs a Company (setup-bench.sh completes the wizard)."""

	def setUp(self):
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("No Company on this site; run the ERPNext setup wizard first.")
		settings(billing_company=company, billing_item=None)

	def test_paid_plan_gets_subscription_plan_and_tenant_subscription(self):
		from saas_control.billing import change_plan, start_billing, stop_billing

		currency = frappe.db.get_value(
			"Company", frappe.db.get_single_value("SaaS Settings", "billing_company"), "default_currency"
		)
		paid = plan("Test Pro", price=49, currency=currency)
		subscription_plan = frappe.db.get_value("SaaS Plan", paid, "subscription_plan")
		self.assertTrue(subscription_plan)
		self.assertEqual(frappe.db.get_value("Subscription Plan", subscription_plan, "cost"), 49)

		doc = tenant("payco", status="Trial", plan=paid, trial_ends_on=add_days(nowdate(), 14))
		name = start_billing(doc)
		doc.reload()
		subscription = frappe.get_doc("Subscription", name)
		self.assertEqual((subscription.party, subscription.status), (doc.customer, "Trialing"))
		self.assertEqual(lifecycle._billing_status(doc), "Trial")

		bigger = plan("Test Pro Plus", price=99, currency=currency)
		doc.db_set("plan", bigger)
		change_plan(doc)
		subscription.reload()
		self.assertEqual(
			subscription.plans[0].plan, frappe.db.get_value("SaaS Plan", bigger, "subscription_plan")
		)

		stop_billing(doc)
		self.assertEqual(frappe.db.get_value("Subscription", name, "status"), "Cancelled")
		self.assertEqual(lifecycle._billing_status(doc), "Suspended")

	def test_free_plan_has_no_subscription(self):
		from saas_control.billing import start_billing

		self.assertIsNone(start_billing(tenant("freeco")))


class TestRoutesRouterRelay(ControlTestCase):
	def call_sync(self, site, key, ids):
		set_request(
			method="POST", path="/", headers={"X-Tenant-Site": site, "Authorization": f"Bearer {key}"}
		)
		return routes.sync("Meta", ids)

	def test_route_sync_auth_conflicts_and_release(self):
		a, b = tenant("alpha"), tenant("beta")
		with self.assertRaises(frappe.AuthenticationError):
			self.call_sync(a.site_name, "wrong", ["p1"])
		self.assertEqual(
			self.call_sync(a.site_name, "key-alpha", ["p1", "ig1"]),
			{"registered": ["ig1", "p1"], "conflicts": []},
		)
		self.assertEqual(
			self.call_sync(b.site_name, "key-beta", ["p1", "p2"]), {"registered": ["p2"], "conflicts": ["p1"]}
		)
		self.call_sync(a.site_name, "key-alpha", ["ig1"])  # alpha drops p1...
		self.assertEqual(
			self.call_sync(b.site_name, "key-beta", ["p1", "p2"])["conflicts"], []
		)  # ...so beta can take it
		a.db_set("status", "Archived")
		self.assertEqual(
			self.call_sync(b.site_name, "key-beta", ["ig1"])["conflicts"], []
		)  # archived tenants release IDs

	def test_router_forwards_signed_deliveries_to_route_owners(self):
		a = tenant("alpha")
		self.call_sync(a.site_name, "key-alpha", ["page-a"])
		body = json.dumps({"object": "page", "entry": [{"id": "page-a"}, {"id": "unrouted"}]}).encode()
		signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

		with patch.dict(frappe.local.conf, {"erp_social_meta_app_secret": SECRET}):
			set_request(method="POST", path="/", data=body, headers={"X-Hub-Signature-256": signature})
			with capture_enqueue() as jobs:
				self.assertEqual(router.meta().get_data(as_text=True), "EVENT_RECEIVED")
			self.assertEqual([j[1]["tenant_name"] for j in jobs], ["alpha"])

			set_request(method="POST", path="/", data=body, headers={"X-Hub-Signature-256": "sha256=forged"})
			self.assertEqual(router.meta().status_code, 403)

		with (
			patch("requests.post", return_value=MagicMock(ok=True, status_code=200)) as post,
			patch("time.sleep"),
		):
			router.forward_delivery("alpha", body.decode(), signature)
		args, kwargs = post.call_args
		self.assertEqual(args[0], "https://alpha.example.test/api/method/erp_social.api.webhooks.meta")
		self.assertEqual((kwargs["data"], kwargs["headers"]["X-Hub-Signature-256"]), (body, signature))

	def test_router_verification(self):
		query = {"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "99"}
		with patch.dict(frappe.local.conf, {"erp_social_meta_verify_token": "vt"}):
			set_request(method="GET", path="/", query_string=query)
			frappe.local.form_dict = frappe._dict(query)
			self.assertEqual(router.meta().get_data(as_text=True), "99")

	def test_forward_retries_server_errors_then_logs(self):
		tenant("alpha")
		with (
			patch("requests.post", return_value=MagicMock(ok=False, status_code=502)) as post,
			patch("time.sleep"),
			patch("frappe.log_error") as log,
		):
			router.forward_delivery("alpha", "{}", "sha256=x")
		self.assertEqual(post.call_count, len(router.RETRY_DELAYS))
		log.assert_called_once()

	def test_tls_ask_allows_only_live_sites(self):
		from saas_control.api import tls

		tenant("alpha")
		tenant("gone", status="Archived")
		self.assertEqual(tls.allowed("alpha.example.test").status_code, 200)
		self.assertEqual(tls.allowed(frappe.local.site).status_code, 200)
		self.assertEqual(tls.allowed("gone.example.test").status_code, 404)
		self.assertEqual(tls.allowed("evil.example.com").status_code, 404)
		self.assertEqual(tls.allowed("").status_code, 404)

	def test_oauth_relay_only_to_live_tenants(self):
		tenant("alpha")
		set_request(method="GET", path="/", query_string={"code": "c", "state": "alpha.example.test~xyz"})
		response = relay.meta_oauth()
		self.assertTrue(
			location(response).startswith(
				"https://alpha.example.test/api/method/erp_social.api.oauth.meta_callback?"
			)
		)
		self.assertIn("code=c", location(response))

		set_request(method="GET", path="/", query_string={"code": "c", "state": "evil.example.com~xyz"})
		self.assertEqual(relay.meta_oauth().status_code, 400)
