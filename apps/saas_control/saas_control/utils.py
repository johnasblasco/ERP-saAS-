"""Pure helpers (no Frappe imports) so they unit-test without a bench."""

import hashlib
import hmac
import json
import re

SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])$")

# ERPNext Subscription.status -> Tenant.status
SUBSCRIPTION_STATUS_MAP = {
	"Trialing": "Trial",
	"Active": "Active",
	"Grace Period": "Past Due",
	"Unpaid": "Suspended",
	"Cancelled": "Suspended",
	"Completed": "Suspended",
}


def normalize_subdomain(value: str | None) -> str:
	return (value or "").strip().lower()


def subdomain_error(subdomain: str, reserved: list[str]) -> str | None:
	"""Why a subdomain can't be used, or None when it's fine."""
	if not SUBDOMAIN_RE.match(subdomain):
		return "Use 3-32 lowercase letters, numbers or hyphens, starting and ending with a letter or number."
	if "--" in subdomain:
		return "Hyphens can't be next to each other."
	if subdomain in reserved:
		return "That name is reserved."
	return None


def site_url(site_name: str, scheme: str = "https", port: int | None = None) -> str:
	default_port = {"https": 443, "http": 80}.get(scheme)
	suffix = f":{port}" if port and port != default_port else ""
	return f"{scheme}://{site_name}{suffix}"


def verify_meta_signature(body: bytes, signature_header: str | None, app_secret: str) -> bool:
	if not signature_header or not app_secret:
		return False
	algo, _, received = signature_header.partition("=")
	if algo != "sha256" or not received:
		return False
	expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
	return hmac.compare_digest(expected, received.strip())


def meta_entry_ids(body: bytes) -> list[str]:
	"""Page / Instagram account IDs a Meta delivery is about."""
	try:
		payload = json.loads(body or b"{}")
	except ValueError:
		return []
	if not isinstance(payload, dict):
		return []
	return sorted({str(e["id"]) for e in payload.get("entry") or [] if isinstance(e, dict) and e.get("id")})


def parse_execute_output(output: str):
	"""`bench execute` prints the function's return value as JSON on its last line."""
	for line in reversed((output or "").strip().splitlines()):
		line = line.strip()
		if line.startswith(("{", "[")):
			try:
				return json.loads(line)
			except ValueError:
				continue
	return None
