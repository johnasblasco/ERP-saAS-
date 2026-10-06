import frappe
import requests
from frappe.tests import IntegrationTestCase

from erp_social.social_integration.events import log_event
from erp_social.social_integration.lead_sync import process_meta_lead_event, process_tiktok_lead_event
from erp_social.social_integration.messaging import process_message_event, send_reply
from erp_social.tests.fakes import FakeResponse, fake_http, make_account, set_social_settings


def graph_lead(field_data):
	return {"id": "x", "field_data": field_data}


class TestMetaLeads(IntegrationTestCase):
	def setUp(self):
		set_social_settings()
		self.account = make_account()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_creates_lead_from_graph_api(self):
		event = log_event("Facebook", self.account.name, "leadgen", "lg-1", {})
		answers = [
			{"name": "full_name", "values": ["Maria Clara"]},
			{"name": "email", "values": ["maria.clara.erp-social@example.com"]},
		]
		with fake_http({("GET", r"/v26\.0/lg-1$"): graph_lead(answers)}) as http:
			process_meta_lead_event(event.name)

		event.reload()
		self.assertEqual(event.status, "Processed", event.error)
		lead = frappe.get_doc("Lead", event.lead)
		self.assertEqual((lead.first_name, lead.last_name), ("Maria", "Clara"))
		params = http.calls[0]["params"]
		self.assertEqual(params["access_token"], "page-token")
		self.assertIn("appsecret_proof", params)

	def test_reuses_existing_lead_with_same_email(self):
		email = "repeat.erp-social@example.com"
		existing = frappe.get_doc({"doctype": "Lead", "first_name": "Repeat", "email_id": email}).insert()
		event = log_event("Facebook", self.account.name, "leadgen", "lg-2", {})
		with fake_http({("GET", r"/lg-2$"): graph_lead([{"name": "email", "values": [email]}])}):
			process_meta_lead_event(event.name)

		event.reload()
		self.assertEqual((event.status, event.lead), ("Processed", existing.name), event.error)

	def test_marks_event_failed_on_graph_error(self):
		event = log_event("Facebook", self.account.name, "leadgen", "lg-3", {})
		error = FakeResponse(400, {"error": {"message": "Invalid leadgen id", "code": 100}})
		with fake_http({("GET", r"/lg-3$"): error}):
			process_meta_lead_event(event.name)

		event.reload()
		self.assertEqual(event.status, "Failed")
		self.assertIn("Graph API returned 400: Invalid leadgen id", event.error)

	def test_network_error_does_not_leak_access_token(self):
		event = log_event("Facebook", self.account.name, "leadgen", "lg-4", {})
		leak = requests.ConnectionError(
			"GET https://graph.facebook.com/v26.0/lg-4?access_token=page-token failed"
		)
		with fake_http({("GET", r"/lg-4$"): leak}):
			process_meta_lead_event(event.name)

		event.reload()
		self.assertEqual(event.status, "Failed")
		self.assertIn("Could not reach the Graph API (ConnectionError)", event.error)
		self.assertNotIn("page-token", event.error)

	def test_duplicate_enabled_ids_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_account("Test FB Page Copy")
		with self.assertRaises(frappe.ValidationError):
			make_account("Test FB Page IG Copy", external_id="page-other", instagram_account_id="ig-2002")


class TestTikTokLeads(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_creates_lead_from_webhook_answers(self):
		account = make_account(
			"Test TikTok", platform="TikTok", external_id="adv-1", instagram_account_id=None
		)
		lead_payload = {
			"lead_id": "tt-1",
			"answers": {"Name": "Jose Rizal", "Email": "jose.erp-social@example.com"},
		}
		event = log_event("TikTok", account.name, "tiktok_lead", "tt-1", lead_payload)
		process_tiktok_lead_event(event.name)

		event.reload()
		self.assertEqual(event.status, "Processed", event.error)
		lead = frappe.get_doc("Lead", event.lead)
		self.assertEqual(
			(lead.first_name, lead.last_name, lead.email_id), ("Jose", "Rizal", "jose.erp-social@example.com")
		)


class TestMessaging(IntegrationTestCase):
	def setUp(self):
		set_social_settings()
		self.account = make_account()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def message_event(self, mid="m-1", platform="Instagram", sender="igsid-77"):
		payload = {
			"platform": platform,
			"account_id": "ig-2002",
			"sender_id": sender,
			"mid": mid,
			"text": "Hi, is this <b>available</b>?",
			"attachments": ["https://cdn.example.com/a.jpg"],
			"timestamp": 1760000000000,
		}
		return log_event(platform, self.account.name, "message", mid, payload)

	def test_first_message_creates_contact_lead_and_communication(self):
		event = self.message_event()
		with fake_http({("GET", r"/igsid-77$"): {"name": "Andres Bonifacio", "username": "andres"}}):
			process_message_event(event.name)

		event.reload()
		self.assertEqual(event.status, "Processed", event.error)
		contact = frappe.get_doc("Social Contact", event.contact)
		self.assertEqual(
			(contact.full_name, contact.username, contact.platform),
			("Andres Bonifacio", "andres", "Instagram"),
		)
		self.assertEqual(contact.lead, event.lead)
		comm = frappe.get_doc("Communication", event.communication)
		self.assertEqual((comm.reference_doctype, comm.reference_name), ("Lead", event.lead))
		self.assertEqual(comm.sent_or_received, "Received")
		self.assertIn("&lt;b&gt;available&lt;/b&gt;", comm.content)  # text is escaped, not rendered
		self.assertIn("https://cdn.example.com/a.jpg", comm.content)

	def test_second_message_reuses_contact_without_profile_lookup(self):
		with fake_http({("GET", r"/igsid-77$"): {"name": "Andres Bonifacio"}}):
			process_message_event(self.message_event("m-1").name)
		with fake_http({}) as http:  # any HTTP call would fail the test
			process_message_event(self.message_event("m-2").name)
		self.assertEqual(http.calls, [])
		self.assertEqual(frappe.db.count("Social Contact", {"external_user_id": "igsid-77"}), 1)

	def test_profile_lookup_failure_still_records_message(self):
		error = FakeResponse(400, {"error": {"message": "no permission", "code": 200}})
		event = self.message_event(platform="Facebook", sender="psid-9")
		with fake_http({("GET", r"/psid-9$"): error}):
			process_message_event(event.name)
		event.reload()
		self.assertEqual(event.status, "Processed", event.error)
		self.assertTrue(
			frappe.db.get_value("Social Contact", event.contact, "full_name").startswith("Facebook user")
		)

	def test_send_reply_posts_through_page_and_logs_communication(self):
		with fake_http({("GET", r"/igsid-77$"): {"name": "Andres Bonifacio"}}):
			process_message_event(self.message_event().name)
		lead = frappe.db.get_value("Social Contact", {"external_user_id": "igsid-77"}, "lead")

		with fake_http({("POST", r"/page-1001/messages$"): {"message_id": "out-1"}}) as http:
			send_reply(lead, "Yes, it is!")

		body = http.calls[0]["json"]
		self.assertEqual(body["recipient"], {"id": "igsid-77"})
		self.assertEqual(body["message"], {"text": "Yes, it is!"})
		self.assertTrue(
			frappe.db.exists("Communication", {"reference_name": lead, "sent_or_received": "Sent"})
		)

	def test_send_reply_explains_24_hour_window(self):
		with fake_http({("GET", r"/igsid-77$"): {"name": "A B"}}):
			process_message_event(self.message_event().name)
		lead = frappe.db.get_value("Social Contact", {"external_user_id": "igsid-77"}, "lead")
		error = FakeResponse(400, {"error": {"message": "outside allowed window", "code": 10}})
		with (
			fake_http({("POST", r"/messages$"): error}),
			self.assertRaisesRegex(frappe.ValidationError, "24 hours"),
		):
			send_reply(lead, "late reply")
