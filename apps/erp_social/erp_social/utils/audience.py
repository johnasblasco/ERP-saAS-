"""Normalize and hash customer identifiers for ad-platform Custom Audiences. No Frappe imports.

Both Meta and TikTok match on SHA-256 of normalized values; raw emails/phones never leave the site.
"""

import hashlib
import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def sha256(value: str) -> str:
	return hashlib.sha256(value.encode()).hexdigest()


def normalize_email(email: str | None) -> str | None:
	email = (email or "").strip().lower()
	return email if EMAIL_RE.match(email) else None


def normalize_phone(phone: str | None, default_country_code: str | None = None) -> str | None:
	"""Digits only, with country code. `+63 917 123 4567` -> `639171234567`.

	Numbers without an international prefix get `default_country_code` (e.g. "63") with the
	trunk `0` dropped; without a default they're used as-is.
	"""
	raw = (phone or "").strip()
	digits = re.sub(r"\D", "", raw)
	if not digits:
		return None
	if raw.startswith("+"):
		pass
	elif digits.startswith("00"):
		digits = digits[2:]
	elif default_country_code:
		cc = re.sub(r"\D", "", default_country_code)
		if not digits.startswith(cc):
			digits = cc + digits.lstrip("0")
	return digits if 7 <= len(digits) <= 15 else None


def meta_rows(contacts: list[dict], default_country_code: str | None = None) -> list[list[str]]:
	"""contacts [{"email", "phone"}] -> deduplicated Meta rows [[sha(email) | "", sha(phone) | ""]]."""
	rows, seen = [], set()
	for contact in contacts:
		email = normalize_email(contact.get("email"))
		phone = normalize_phone(contact.get("phone"), default_country_code)
		if not (email or phone):
			continue
		row = [sha256(email) if email else "", sha256(phone) if phone else ""]
		if tuple(row) not in seen:
			seen.add(tuple(row))
			rows.append(row)
	return rows


def tiktok_email_file(contacts: list[dict]) -> bytes:
	"""One SHA-256 hashed email per line (TikTok calculate_type EMAIL_SHA256)."""
	hashes = sorted({sha256(e) for e in (normalize_email(c.get("email")) for c in contacts) if e})
	return "\n".join(hashes).encode()
