from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request

from saas_tenant import api, guard
from saas_tenant.setup import initialize


def set_plan(**values):
	for field, value in {"plan_name": "Starter", "status": "Active", "max_users": 0, **values}.items():
		frappe.db.set_single_value("SaaS Subscription", field, value)
	frappe.local.cache.pop("saas_subscription", None)


def make_user(email, enabled=1):
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True)
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "T",
			"enabled": enabled,
			"send_welcome_email": 0,
			"roles": [{"role": "System Manager"}],
		}
	).insert(ignore_permissions=True)


class TestSaaSTenant(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.local.cache.pop("saas_subscription", None)

	def test_user_limit(self):
		current = guard_users()
		set_plan(max_users=current + 1)
		make_user("limit-one@example.com")
		with self.assertRaisesRegex(frappe.ValidationError, "includes"):
			make_user("limit-two@example.com")
		disabled = make_user("limit-disabled@example.com", enabled=0)  # disabled users don't count
		disabled.reload()
		disabled.first_name = "Edited"
		disabled.save(ignore_permissions=True)

	def test_unlimited_plan(self):
		set_plan(max_users=0)
		make_user("unlimited-a@example.com")
		make_user("unlimited-b@example.com")

	def test_suspended_blocks_api_but_not_webhooks(self):
		set_plan(status="Suspended", support_email="billing@example.com")
		frappe.set_user("someone@example.com")
		set_request(method="GET", path="/api/resource/ToDo")
		with self.assertRaisesRegex(guard.SubscriptionSuspended, "billing@example.com"):
			guard.before_request()
		set_request(method="POST", path="/api/method/erp_social.api.webhooks.meta")
		guard.before_request()
		set_request(method="GET", path="/app/todo")
		guard.before_request()  # pages render; the desk shows the notice

	def test_active_does_not_block(self):
		set_plan(status="Active")
		frappe.set_user("someone@example.com")
		set_request(method="GET", path="/api/resource/ToDo")
		guard.before_request()

	def test_update_subscription_requires_key(self):
		set_request(method="POST", path="/", headers={"Authorization": "Bearer wrong"})
		with patch.dict(frappe.local.conf, {"saas_tenant_key": "right"}):
			with self.assertRaises(frappe.AuthenticationError):
				api.update_subscription(plan_name="Pro", status="Active")
			set_request(method="POST", path="/", headers={"Authorization": "Bearer right"})
			api.update_subscription(plan_name="Pro", status="Past Due", max_users=5)
			self.assertEqual(guard.subscription()["status"], "Past Due")
			self.assertEqual(guard.subscription()["max_users"], 5)
			usage = api.usage()
		self.assertIn("active_users", usage)
		self.assertGreaterEqual(usage["db_size_mb"], 0)

	def test_no_key_configured_rejects_everything(self):
		set_request(method="POST", path="/", headers={"Authorization": "Bearer "})
		with patch.dict(frappe.local.conf, {"saas_tenant_key": None}):
			with self.assertRaises(frappe.AuthenticationError):
				api.usage()

	def test_initialize_creates_owner(self):
		with patch("frappe.db.commit"):
			result = initialize("owner-x@example.com", "Owner Person", "Starter", "Trial", 3, "2030-01-01")
		self.assertIn("/update-password?key=", result["setup_link"])
		user = frappe.get_doc("User", "owner-x@example.com")
		self.assertIn("System Manager", [r.role for r in user.roles])
		self.assertEqual(guard.subscription()["status"], "Trial")


def guard_users():
	from saas_tenant.limits import active_system_users

	return active_system_users()
