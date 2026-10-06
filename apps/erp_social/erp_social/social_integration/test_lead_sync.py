from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from erp_social.social_integration.lead_sync import process_meta_lead_event

PAGE_ID = "test-page-1001"


def make_account(**overrides):
	values = {
		"doctype": "Social Platform Account",
		"account_name": "Test FB Page",
		"platform": "Facebook",
		"external_id": PAGE_ID,
		"app_secret": "app-secret",
		"verify_token": "verify-me",
		"access_token": "page-token",
	}
	values.update(overrides)
	name = values["account_name"]
	if frappe.db.exists("Social Platform Account", name):
		frappe.delete_doc("Social Platform Account", name, force=True)
	return frappe.get_doc(values).insert(ignore_permissions=True)


def make_event(account, leadgen_id):
	return frappe.get_doc(
		{
			"doctype": "Social Lead Event",
			"platform": "Facebook",
			"account": account.name,
			"event_type": "leadgen",
			"external_id": leadgen_id,
			"payload": "{}",
		}
	).insert(ignore_permissions=True)


def graph_response(field_data, status=200):
	response = MagicMock(ok=status == 200, status_code=status, text="error body")
	response.json.return_value = {"id": "x", "field_data": field_data}
	return response


class TestLeadSync(IntegrationTestCase):
	def setUp(self):
		self.account = make_account()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_creates_lead_from_graph_api(self):
		event = make_event(self.account, "lg-1")
		answers = [
			{"name": "full_name", "values": ["Maria Clara"]},
			{"name": "email", "values": ["maria.clara.erp-social@example.com"]},
		]
		with patch(
			"erp_social.social_integration.lead_sync.requests.get", return_value=graph_response(answers)
		) as get:
			process_meta_lead_event(event.name)

		event.reload()
		self.assertEqual(event.status, "Processed", event.error)
		lead = frappe.get_doc("Lead", event.lead)
		self.assertEqual(lead.first_name, "Maria")
		self.assertEqual(lead.last_name, "Clara")
		self.assertEqual(lead.email_id, "maria.clara.erp-social@example.com")

		url = get.call_args.args[0]
		self.assertIn("/v23.0/lg-1", url)
		self.assertIn("appsecret_proof", get.call_args.kwargs["params"])

	def test_reuses_existing_lead_with_same_email(self):
		email = "repeat.erp-social@example.com"
		existing = frappe.get_doc({"doctype": "Lead", "first_name": "Repeat", "email_id": email}).insert()
		event = make_event(self.account, "lg-2")
		answers = [{"name": "email", "values": [email]}]
		with patch(
			"erp_social.social_integration.lead_sync.requests.get", return_value=graph_response(answers)
		):
			process_meta_lead_event(event.name)

		event.reload()
		self.assertEqual(event.status, "Processed", event.error)
		self.assertEqual(event.lead, existing.name)

	def test_marks_event_failed_on_graph_error(self):
		event = make_event(self.account, "lg-3")
		with patch(
			"erp_social.social_integration.lead_sync.requests.get", return_value=graph_response([], 400)
		):
			process_meta_lead_event(event.name)

		event.reload()
		self.assertEqual(event.status, "Failed")
		self.assertIn("Graph API returned 400", event.error)

	def test_network_error_does_not_leak_access_token(self):
		event = make_event(self.account, "lg-4")
		leak = requests.ConnectionError(
			"GET https://graph.facebook.com/v23.0/lg-4?access_token=page-token failed"
		)
		with patch("erp_social.social_integration.lead_sync.requests.get", side_effect=leak):
			process_meta_lead_event(event.name)

		event.reload()
		self.assertEqual(event.status, "Failed")
		self.assertIn("Could not reach the Graph API (ConnectionError)", event.error)
		self.assertNotIn("page-token", event.error)

	def test_duplicate_enabled_external_id_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_account(account_name="Test FB Page Copy")
