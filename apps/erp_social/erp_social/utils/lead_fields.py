"""Map lead-form answers from any platform onto ERPNext Lead fields. No Frappe imports."""

import re

# Normalized answer key -> ERPNext Lead field. Keys are lower_snake_case form field names.
FIELD_ALIASES = {
	"first_name": "first_name",
	"given_name": "first_name",
	"last_name": "last_name",
	"surname": "last_name",
	"family_name": "last_name",
	"email": "email_id",
	"email_address": "email_id",
	"work_email": "email_id",
	"phone": "mobile_no",
	"phone_number": "mobile_no",
	"mobile": "mobile_no",
	"mobile_number": "mobile_no",
	"company": "company_name",
	"company_name": "company_name",
	"job_title": "job_title",
	"city": "city",
	"state": "state",
	"province": "state",
	"website": "website",
	# `country` is deliberately absent: Lead.country is a Link, and free-text answers
	# that don't match a Country record would fail link validation.
}
FULL_NAME_KEYS = ("full_name", "name")


def normalize_key(key: str) -> str:
	return re.sub(r"[^a-z0-9]+", "_", (key or "").strip().lower()).strip("_")


def map_answers(answers: dict[str, str]) -> dict:
	"""{"Full Name": "Juan Dela Cruz", "Email": "j@x.com"} -> Lead fields.

	A full name is split into first/last name when those weren't answered separately.
	"""
	clean = {}
	for key, value in (answers or {}).items():
		value = str(value or "").strip()
		if value:
			clean[normalize_key(key)] = value

	lead = {}
	for key, value in clean.items():
		field = FIELD_ALIASES.get(key)
		if field and field not in lead:
			lead[field] = value

	full_name = next((clean[k] for k in FULL_NAME_KEYS if k in clean), None)
	if full_name and not lead.get("first_name"):
		first, _, last = full_name.partition(" ")
		lead["first_name"] = first
		if last.strip() and not lead.get("last_name"):
			lead["last_name"] = last.strip()

	return lead
