"""Webhook signature verification for social platforms.

Pure functions with no Frappe imports so they can be unit-tested anywhere.
"""

import hashlib
import hmac
import time


def verify_meta_signature(body: bytes, signature_header: str | None, app_secret: str) -> bool:
	"""Verify Meta's `X-Hub-Signature-256: sha256=<hex>` header against the raw body."""
	if not signature_header or not app_secret:
		return False
	algo, _, received = signature_header.partition("=")
	if algo != "sha256" or not received:
		return False
	expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
	return hmac.compare_digest(expected, received.strip())


def meta_appsecret_proof(access_token: str, app_secret: str) -> str:
	"""`appsecret_proof` parameter Meta recommends sending with Graph API calls."""
	return hmac.new(app_secret.encode(), access_token.encode(), hashlib.sha256).hexdigest()


def parse_tiktok_signature_header(header: str | None) -> tuple[str, str] | None:
	"""Split `TikTok-Signature: t=<unix ts>,s=<hex>` into (timestamp, signature)."""
	if not header:
		return None
	parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
	timestamp, signature = parts.get("t", "").strip(), parts.get("s", "").strip()
	if not timestamp.isdigit() or not signature:
		return None
	return timestamp, signature


def verify_tiktok_signature(
	body: bytes,
	signature_header: str | None,
	client_secret: str,
	tolerance_seconds: int = 300,
	now: float | None = None,
) -> bool:
	"""Verify TikTok's signature: HMAC-SHA256 of `"{t}.{body}"` keyed with the client secret.

	Rejects timestamps further than `tolerance_seconds` from now to block replays.
	"""
	parsed = parse_tiktok_signature_header(signature_header)
	if not parsed or not client_secret:
		return False
	timestamp, received = parsed
	now = time.time() if now is None else now
	if abs(now - int(timestamp)) > tolerance_seconds:
		return False
	signed_payload = timestamp.encode() + b"." + body
	expected = hmac.new(client_secret.encode(), signed_payload, hashlib.sha256).hexdigest()
	return hmac.compare_digest(expected, received)
