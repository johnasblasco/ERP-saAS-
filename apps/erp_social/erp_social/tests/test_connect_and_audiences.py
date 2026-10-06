from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.tests import IntegrationTestCase

from erp_social.api import oauth
from erp_social.social_integration import routes
from erp_social.social_integration.audiences import sync_audience
from erp_social.tests.fakes import FakeResponse, fake_http, make_account, set_social_settings
from erp_social.utils.audience import sha256

PAGES = {
	"data": [
		{
			"id": "pg-1",
			"name": "Sari-Sari Store",
			"access_token": "pg-1-token",
			"instagram_business_account": {"id": "ig-1", "username": "sarisari"},
		},
		{"id": "pg-2", "name": "Other Page", "access_token": "pg-2-token"},
	]
}


def query_of(response):
	return {k: v[0] for k, v in parse_qs(urlparse(response.headers["Location"]).query).items()}


class TestMetaConnect(IntegrationTestCase):
	def setUp(self):
		set_social_settings()

	def tearDown(self):
		frappe.db.rollback()

	def login(self):
		url = oauth.meta_login_url()
		return parse_qs(urlparse(url).query)["state"][0]

	def test_login_url_requests_needed_scopes(self):
		url = oauth.meta_login_url()
		query = parse_qs(urlparse(url).query)
		self.assertEqual(query["client_id"], ["meta-app"])
		for scope in ("leads_retrieval", "pages_messaging", "instagram_manage_messages", "ads_management"):
			self.assertIn(scope, query["scope"][0])

	def test_full_connect_flow(self):
		state = self.login()
		routes_ = {
			("GET", r"/oauth/access_token$"): lambda m, u, **kw: {
				"access_token": "long" if kw["params"].get("grant_type") else "short",
				"expires_in": 5184000,
			},
			("GET", r"/me/accounts$"): PAGES,
			("GET", r"/me/adaccounts$"): {"data": [{"account_id": "55", "name": "Main Ads"}]},
			("POST", r"/pg-1/subscribed_apps$"): {"success": True},
		}
		with fake_http(routes_) as http:
			response = oauth.meta_callback(code="abc", state=state)
			params = query_of(response)
			self.assertEqual(params["platform"], "meta")

			pending = oauth.meta_pending(params["pending"])
			self.assertEqual([p["id"] for p in pending["pages"]], ["pg-1", "pg-2"])
			self.assertNotIn("access_token", str(pending))  # tokens never reach the browser

			results = oauth.meta_connect(params["pending"], '["pg-1"]', ad_account_id="55")

		self.assertEqual(results, [{"account": "Sari-Sari Store", "ok": True}])
		account = frappe.get_doc("Social Platform Account", "Sari-Sari Store")
		self.assertEqual(
			(account.external_id, account.instagram_account_id, account.ad_account_id), ("pg-1", "ig-1", "55")
		)
		self.assertEqual(account.get_password("access_token"), "pg-1-token")
		self.assertEqual(account.get_password("user_access_token"), "long")
		self.assertTrue(account.webhook_subscribed)
		self.assertEqual(
			http.find("POST", r"/pg-1/subscribed_apps$")[0]["data"], {"subscribed_fields": "leadgen,messages"}
		)

		with self.assertRaises(frappe.ValidationError):  # pending data is single-use
			oauth.meta_pending(params["pending"])

	def test_state_is_single_use_and_bound_to_user(self):
		state = self.login()
		with fake_http(
			{("GET", r"oauth/access_token"): {"access_token": "t"}, ("GET", r"me/"): {"data": []}}
		):
			oauth.meta_callback(code="abc", state=state)
			replay = oauth.meta_callback(code="abc", state=state)
		self.assertIn("error", query_of(replay))

	def test_callback_error_is_shown_on_connect_page(self):
		state = self.login()
		response = oauth.meta_callback(
			error="access_denied", error_description="Permissions error", state=state
		)
		self.assertEqual(query_of(response)["error"], "Permissions error")


class TestTikTokConnect(IntegrationTestCase):
	def setUp(self):
		set_social_settings()

	def tearDown(self):
		frappe.db.rollback()

	def test_full_connect_flow_subscribes_lead_webhook(self):
		state = parse_qs(urlparse(oauth.tiktok_login_url()).query)["state"][0]
		routes_ = {
			("POST", r"/oauth2/access_token/$"): {
				"code": 0,
				"data": {"access_token": "tt-token", "advertiser_ids": ["adv-1"]},
			},
			("GET", r"/oauth2/advertiser/get/$"): {
				"code": 0,
				"data": {"list": [{"advertiser_id": "adv-1", "advertiser_name": "My Shop Ads"}]},
			},
			("POST", r"/subscription/subscribe/$"): {"code": 0, "data": {"subscription_id": "sub-1"}},
		}
		with fake_http(routes_) as http:
			params = query_of(oauth.tiktok_callback(auth_code="code", state=state))
			self.assertEqual(oauth.tiktok_pending(params["pending"])["advertisers"][0]["name"], "My Shop Ads")
			oauth.tiktok_connect(params["pending"], ["adv-1"])

		account = frappe.get_doc("Social Platform Account", "My Shop Ads")
		self.assertEqual(
			(account.platform, account.tiktok_subscription_id, account.webhook_subscribed),
			("TikTok", "sub-1", 1),
		)
		body = http.find("POST", r"/subscription/subscribe/$")[0]["json"]
		self.assertEqual(body["subscribe_entity"], "LEAD")
		self.assertIn("erp_social.api.webhooks.tiktok?token=", body["callback_url"])

	def test_tiktok_error_code_is_reported(self):
		state = parse_qs(urlparse(oauth.tiktok_login_url()).query)["state"][0]
		with fake_http(
			{("POST", r"/oauth2/access_token/$"): {"code": 40001, "message": "auth_code expired"}}
		):
			params = query_of(oauth.tiktok_callback(auth_code="old", state=state))
		self.assertIn("auth_code expired", params["error"])


class TestAudiences(IntegrationTestCase):
	def setUp(self):
		set_social_settings(default_country_code="63")
		self.account = make_account(ad_account_id="act_55", user_access_token="user-token")
		frappe.get_doc(
			{
				"doctype": "Lead",
				"first_name": "Aud",
				"email_id": " Aud.Lead@Example.com ",
				"mobile_no": "09171234567",
			}
		).insert()

	def tearDown(self):
		frappe.db.rollback()

	def audience(self, account, name="Test Audience"):
		if frappe.db.exists("Social Audience", name):
			frappe.delete_doc("Social Audience", name, force=True)
		return frappe.get_doc(
			{"doctype": "Social Audience", "audience_name": name, "account": account.name, "source": "Leads"}
		).insert()

	def test_meta_audience_created_and_hashed_users_uploaded(self):
		audience = self.audience(self.account)
		routes_ = {
			("POST", r"/act_55/customaudiences$"): {"id": "aud-1"},
			("POST", r"/aud-1/users$"): {"num_received": 1},
		}
		with fake_http(routes_) as http, patch("frappe.db.commit"):
			sync_audience(audience.name)

		audience.reload()
		self.assertEqual((audience.status, audience.audience_id), ("Synced", "aud-1"), audience.error)
		payload = http.find("POST", r"/aud-1/users$")[0]["data"]["payload"]
		self.assertIn(sha256("aud.lead@example.com"), payload)
		self.assertIn(sha256("639171234567"), payload)
		self.assertNotIn('example.com"', payload)  # nothing unhashed leaves the site

	def test_missing_ad_account_marks_failed(self):
		self.account.ad_account_id = ""
		self.account.save()
		audience = self.audience(self.account)
		with fake_http({}), patch("frappe.db.commit"):
			sync_audience(audience.name)
		audience.reload()
		self.assertEqual(audience.status, "Failed")
		self.assertIn("Ad Account ID", audience.error)

	def test_tiktok_audience_uploads_email_file(self):
		account = make_account(
			"Test TikTok Ads", platform="TikTok", external_id="adv-5", instagram_account_id=None
		)
		audience = self.audience(account, "TikTok Audience")
		routes_ = {
			("POST", r"/dmp/custom_audience/file/upload/$"): {"code": 0, "data": {"file_path": "fp-1"}},
			("POST", r"/dmp/custom_audience/create/$"): {
				"code": 0,
				"data": {"custom_audience_id": "ttaud-1"},
			},
		}
		with fake_http(routes_) as http, patch("frappe.db.commit"):
			sync_audience(audience.name)
		audience.reload()
		self.assertEqual((audience.status, audience.audience_id), ("Synced", "ttaud-1"), audience.error)
		upload = http.find("POST", r"/file/upload/$")[0]
		self.assertEqual(upload["data"]["calculate_type"], "EMAIL_SHA256")
		self.assertIn(sha256("aud.lead@example.com").encode(), upload["files"]["file"][1])
		self.assertEqual(http.find("POST", r"/create/$")[0]["json"]["file_paths"], ["fp-1"])


class TestControlPlaneRoutes(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_sync_posts_owned_meta_ids(self):
		make_account()
		conf = {"saas_control_url": "https://control.example.com/", "saas_tenant_key": "tenant-key"}
		with (
			patch.dict(frappe.local.conf, conf),
			patch("requests.post", return_value=FakeResponse(200, {})) as post,
		):
			routes.sync_routes()
		args, kwargs = post.call_args
		self.assertEqual(args[0], "https://control.example.com/api/method/saas_control.api.routes.sync")
		self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tenant-key")
		self.assertIn("page-1001", kwargs["json"]["external_ids"])
		self.assertIn("ig-2002", kwargs["json"]["external_ids"])

	def test_redirects_go_through_control_site(self):
		from erp_social.integrations import config

		with patch.dict(
			frappe.local.conf, {"saas_control_url": "https://control.example.com", "saas_tenant_key": "k"}
		):
			self.assertEqual(
				config.meta_oauth_redirect_uri(),
				"https://control.example.com/api/method/saas_control.api.relay.meta_oauth",
			)
			self.assertTrue(oauth._new_state("meta").startswith(frappe.local.site + "~"))
