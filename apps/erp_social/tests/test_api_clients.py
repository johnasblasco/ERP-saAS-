from urllib.parse import parse_qs, urlparse

import pytest
import requests

from erp_social.integrations.meta_api import MetaAPIError, MetaClient
from erp_social.integrations.tiktok_api import TikTokAPIError, TikTokClient


class Resp:
	def __init__(self, status=200, payload=None, text=""):
		self.status_code, self.ok, self._payload, self.text = status, 200 <= status < 300, payload, text

	def json(self):
		if self._payload is None:
			raise ValueError
		return self._payload


class Session:
	def __init__(self, result):
		self.result, self.calls = result, []

	def request(self, method, url, **kwargs):
		self.calls.append((method, url, kwargs))
		if isinstance(self.result, Exception):
			raise self.result
		return self.result


def test_meta_login_url():
	url = MetaClient("app", "secret", "v26.0").login_url("https://x/cb", "st8")
	query = parse_qs(urlparse(url).query)
	assert url.startswith("https://www.facebook.com/v26.0/dialog/oauth?")
	assert (
		query["client_id"] == ["app"]
		and query["state"] == ["st8"]
		and query["redirect_uri"] == ["https://x/cb"]
	)


def test_meta_request_signs_token_and_returns_body():
	session = Session(Resp(200, {"id": "1"}))
	assert MetaClient("app", "secret", session=session).get_lead("1", "tok") == {"id": "1"}
	method, url, kwargs = session.calls[0]
	assert (method, url) == ("GET", "https://graph.facebook.com/v26.0/1")
	assert kwargs["params"]["access_token"] == "tok" and len(kwargs["params"]["appsecret_proof"]) == 64


def test_meta_error_message_and_code():
	session = Session(Resp(400, {"error": {"message": "Bad", "code": 190}}))
	with pytest.raises(MetaAPIError) as err:
		MetaClient("a", "s", session=session).get_lead("1", "tok")
	assert str(err.value) == "Graph API returned 400: Bad" and err.value.code == 190


def test_meta_network_error_hides_token_and_chain():
	session = Session(requests.ConnectionError("https://graph.facebook.com/1?access_token=SECRET"))
	with pytest.raises(MetaAPIError) as err:
		MetaClient("a", "s", session=session).get_lead("1", "SECRET")
	assert "SECRET" not in str(err.value)
	assert err.value.__context__ is None and err.value.__cause__ is None


def test_meta_audience_batches():
	session = Session(Resp(200, {"num_received": 2}))
	rows = [["a", "b"]] * 10001
	assert MetaClient("a", "s", session=session).add_audience_users("aud", rows, "tok") == 4
	assert len(session.calls) == 2


def test_tiktok_error_code_with_http_200():
	session = Session(Resp(200, {"code": 40100, "message": "Access token invalid"}))
	with pytest.raises(TikTokAPIError) as err:
		TikTokClient("app", "sec", session=session).list_advertisers("tok")
	assert "Access token invalid" in str(err.value) and err.value.code == 40100


def test_tiktok_access_token_header_and_data():
	session = Session(Resp(200, {"code": 0, "data": {"subscription_id": "s1"}}))
	sub = TikTokClient("app", "sec", session=session).subscribe_leads("adv", "tok", "https://cb")
	method, url, kwargs = session.calls[0]
	assert sub == "s1" and url.endswith("/open_api/v1.3/subscription/subscribe/")
	assert kwargs["json"]["subscription_detail"] == {
		"access_token": "tok",
		"lead_source": "INSTANT_FORM",
		"advertiser_id": "adv",
	}


def test_tiktok_upload_sends_md5_signature():
	session = Session(Resp(200, {"code": 0, "data": {"file_path": "fp"}}))
	assert (
		TikTokClient("a", "s", session=session).upload_audience_file("adv", "tok", b"abc", "EMAIL_SHA256")
		== "fp"
	)
	kwargs = session.calls[0][2]
	assert kwargs["headers"] == {"Access-Token": "tok"}
	assert kwargs["data"]["file_signature"] == "900150983cd24fb0d6963f7d28e17f72"
