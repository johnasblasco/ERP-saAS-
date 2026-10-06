import hashlib
import hmac
import json

from saas_control.utils import (
	meta_entry_ids,
	parse_execute_output,
	site_url,
	subdomain_error,
	verify_meta_signature,
)


def test_subdomain_rules():
	assert subdomain_error("acme", []) is None
	assert subdomain_error("acme-store-2", []) is None
	assert subdomain_error("ab", []) is not None  # too short
	assert subdomain_error("-acme", []) is not None
	assert subdomain_error("acme-", []) is not None
	assert subdomain_error("ac--me", []) is not None
	assert subdomain_error("Acme", []) is not None  # callers lowercase first
	assert subdomain_error("acme.co", []) is not None
	assert subdomain_error("admin", ["admin"]) == "That name is reserved."
	assert subdomain_error("a" * 33, []) is not None


def test_site_url():
	assert site_url("acme.example.com") == "https://acme.example.com"
	assert site_url("acme.localhost", "http", 8000) == "http://acme.localhost:8000"
	assert site_url("acme.example.com", "https", 443) == "https://acme.example.com"


def test_meta_signature():
	body = b'{"entry":[]}'
	sig = "sha256=" + hmac.new(b"s", body, hashlib.sha256).hexdigest()
	assert verify_meta_signature(body, sig, "s")
	assert not verify_meta_signature(body, sig, "other")
	assert not verify_meta_signature(body, None, "s")


def test_meta_entry_ids():
	body = json.dumps({"object": "page", "entry": [{"id": "2"}, {"id": 1}, {"id": "2"}, {}]}).encode()
	assert meta_entry_ids(body) == ["1", "2"]
	assert meta_entry_ids(b"not json") == []
	assert meta_entry_ids(b"[]") == []


def test_parse_execute_output():
	output = 'some warning\n{"setup_link": "https://x/update-password?key=1"}\n'
	assert parse_execute_output(output) == {"setup_link": "https://x/update-password?key=1"}
	assert parse_execute_output("no json here") is None


def test_bench_runner_masks_log_but_returns_raw_output(tmp_path, monkeypatch):
	import subprocess
	import sys
	import types

	sys.modules.setdefault("frappe", types.SimpleNamespace())
	utils = types.ModuleType("frappe.utils")
	utils.get_bench_path = lambda: str(tmp_path)
	monkeypatch.setitem(sys.modules, "frappe.utils", utils)
	from saas_control.bench import BenchRunner

	output = 'ok\n{"setup_link": "http://x/update-password?key=abc123"} secret-key'
	monkeypatch.setattr(
		subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=output, stderr="")
	)
	bench = BenchRunner(str(tmp_path), secrets=["secret-key"])
	assert bench.run("--site", "s", "execute", "x") == output
	log = bench.text_log()
	assert "abc123" not in log and "secret-key" not in log and "update-password?key=********" in log
