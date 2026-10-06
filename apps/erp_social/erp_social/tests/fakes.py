"""Test doubles shared by erp_social integration tests (no network access in tests)."""

import json
import re
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.utils import set_request


class FakeResponse:
	def __init__(self, status_code=200, payload=None, text=None):
		self.status_code = status_code
		self.ok = 200 <= status_code < 300
		self._payload = payload
		self.text = text if text is not None else json.dumps(payload)

	def json(self):
		if self._payload is None:
			raise ValueError("no json")
		return self._payload


class FakeHTTP:
	"""Replaces requests.request. `routes` maps (METHOD, url-regex) -> response, callable or exception."""

	def __init__(self, routes=None):
		self.routes = dict(routes or {})
		self.calls = []

	def __call__(self, method, url, **kwargs):
		self.calls.append({"method": method, "url": url, **kwargs})
		for (route_method, pattern), result in self.routes.items():
			if route_method == method and re.search(pattern, url):
				if isinstance(result, Exception):
					raise result
				if callable(result) and not isinstance(result, FakeResponse):
					result = result(method, url, **kwargs)
				return result if isinstance(result, FakeResponse) else FakeResponse(200, result)
		raise AssertionError(f"Unexpected HTTP call: {method} {url}")

	def find(self, method, pattern):
		return [c for c in self.calls if c["method"] == method and re.search(pattern, c["url"])]


@contextmanager
def fake_http(routes=None):
	http = FakeHTTP(routes)
	with patch("requests.request", http):
		yield http


@contextmanager
def capture_enqueue():
	jobs = []
	with patch("frappe.enqueue", lambda method, **kwargs: jobs.append((method, kwargs))):
		yield jobs


def simulate_request(method, path="/", body=b"", headers=None, query=None):
	set_request(method=method, path=path, data=body, headers=headers or {}, query_string=query or {})
	frappe.local.form_dict = frappe._dict(query or {})


def set_social_settings(**values):
	settings = frappe.get_single("Social Integration Settings")
	settings.update(
		{
			"meta_app_id": "meta-app",
			"meta_app_secret": "meta-secret",
			"meta_verify_token": "meta-verify",
			"tiktok_app_id": "tt-app",
			"tiktok_app_secret": "tt-secret",
			"create_leads_from_messages": 1,
			**values,
		}
	)
	settings.save(ignore_permissions=True)
	return settings


def make_account(account_name="Test FB Page", **values):
	if frappe.db.exists("Social Platform Account", account_name):
		frappe.delete_doc("Social Platform Account", account_name, force=True, ignore_permissions=True)
	doc = {
		"doctype": "Social Platform Account",
		"account_name": account_name,
		"platform": "Facebook",
		"external_id": "page-1001",
		"instagram_account_id": "ig-2002",
		"access_token": "page-token",
		**values,
	}
	return frappe.get_doc(doc).insert(ignore_permissions=True)
