import hashlib
import hmac
import json

import frappe
from frappe.tests import IntegrationTestCase

from erp_social.api import webhooks
from erp_social.integrations.config import tiktok_webhook_token
from erp_social.tests.fakes import capture_enqueue, make_account, set_social_settings, simulate_request


def signed(payload, secret="meta-secret"):
	body = json.dumps(payload).encode()
	return body, {
		"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
	}


LEADGEN = {
	"object": "page",
	"entry": [
		{
			"id": "page-1001",
			"changes": [{"field": "leadgen", "value": {"leadgen_id": "lg-77", "page_id": "page-1001"}}],
		}
	],
}
IG_DM = {
	"object": "instagram",
	"entry": [
		{
			"id": "ig-2002",
			"messaging": [
				{
					"sender": {"id": "igsid-1"},
					"recipient": {"id": "ig-2002"},
					"timestamp": 1,
					"message": {"mid": "mid-1", "text": "hello"},
				},
				{
					"sender": {"id": "ig-2002"},
					"recipient": {"id": "igsid-1"},
					"timestamp": 2,
					"message": {"mid": "mid-2", "text": "echo", "is_echo": True},
				},
			],
		}
	],
}


class TestMetaWebhook(IntegrationTestCase):
	def setUp(self):
		set_social_settings()
		self.account = make_account()

	def tearDown(self):
		frappe.db.rollback()

	def post(self, body, headers):
		simulate_request(
			"POST",
			"/api/method/erp_social.api.webhooks.meta",
			body,
			{"Content-Type": "application/json", **headers},
		)
		with capture_enqueue() as jobs:
			response = webhooks.meta()
		return response, jobs

	def test_verification_challenge(self):
		query = {"hub.mode": "subscribe", "hub.verify_token": "meta-verify", "hub.challenge": "4242"}
		simulate_request("GET", query=query)
		response = webhooks.meta()
		self.assertEqual((response.status_code, response.get_data(as_text=True)), (200, "4242"))

		simulate_request("GET", query={**query, "hub.verify_token": "wrong"})
		self.assertEqual(webhooks.meta().status_code, 403)

	def test_signed_leadgen_is_logged_once_and_enqueued(self):
		body, headers = signed(LEADGEN)
		response, jobs = self.post(body, headers)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(jobs), 1)
		self.assertTrue(jobs[0][0].endswith("process_meta_lead_event"))

		response, jobs = self.post(body, headers)  # Meta retry
		self.assertEqual(jobs, [])
		self.assertEqual(frappe.db.count("Social Lead Event", {"external_id": "lg-77"}), 1)

	def test_forged_signature_is_rejected(self):
		body, _headers = signed(LEADGEN, secret="attacker")
		response, jobs = self.post(body, {"X-Hub-Signature-256": _headers["X-Hub-Signature-256"]})
		self.assertEqual(response.status_code, 403)
		self.assertEqual(jobs, [])
		self.assertFalse(frappe.db.exists("Social Lead Event", {"external_id": "lg-77"}))

	def test_instagram_dm_routes_to_account_by_instagram_id_and_skips_echoes(self):
		body, headers = signed(IG_DM)
		response, jobs = self.post(body, headers)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(jobs), 1)
		event = frappe.get_doc("Social Lead Event", {"external_id": "mid-1"})
		self.assertEqual(
			(event.platform, event.account, event.event_type), ("Instagram", self.account.name, "message")
		)
		self.assertFalse(frappe.db.exists("Social Lead Event", {"external_id": "mid-2"}))

	def test_unknown_page_is_ignored_with_200(self):
		payload = {**LEADGEN, "entry": [{**LEADGEN["entry"][0], "id": "someone-else"}]}
		payload["entry"][0]["changes"][0]["value"] = {"leadgen_id": "lg-x", "page_id": "someone-else"}
		body, headers = signed(payload)
		response, jobs = self.post(body, headers)
		self.assertEqual((response.status_code, response.get_data(as_text=True)), (200, "IGNORED"))

	def test_account_own_app_secret_overrides_shared_secret(self):
		self.account.app_secret = "own-secret"
		self.account.save()
		body, headers = signed(LEADGEN, secret="own-secret")
		response, jobs = self.post(body, headers)
		self.assertEqual((response.status_code, len(jobs)), (200, 1))


class TestTikTokWebhook(IntegrationTestCase):
	def setUp(self):
		set_social_settings()
		self.account = make_account(
			"Test TikTok", platform="TikTok", external_id="adv-9", instagram_account_id=None
		)
		self.payload = {
			"request_id": "r1",
			"object": 1,
			"time": 1760000000,
			"entry": [
				{
					"id": "tt-lead-1",
					"advertiser_id": "adv-9",
					"page_id": "p1",
					"lead_source": "INSTANT_FORM",
					"changes": [
						{"field": "name", "value": "Gabriela Silang"},
						{"field": "email", "value": "g@example.com"},
					],
				}
			],
		}

	def tearDown(self):
		frappe.db.rollback()

	def post(self, token):
		simulate_request(
			"POST",
			"/api/method/erp_social.api.webhooks.tiktok",
			json.dumps(self.payload).encode(),
			{"Content-Type": "application/json"},
			query={"token": token},
		)
		with capture_enqueue() as jobs:
			response = webhooks.tiktok()
		return response, jobs

	def test_wrong_token_is_rejected(self):
		response, jobs = self.post("nope")
		self.assertEqual((response.status_code, jobs), (403, []))

	def test_valid_lead_is_logged_with_answers(self):
		response, jobs = self.post(tiktok_webhook_token())
		self.assertEqual((response.status_code, len(jobs)), (200, 1))
		event = frappe.get_doc("Social Lead Event", {"external_id": "tt-lead-1"})
		payload = json.loads(event.payload)
		self.assertEqual(payload["answers"], {"name": "Gabriela Silang", "email": "g@example.com"})
