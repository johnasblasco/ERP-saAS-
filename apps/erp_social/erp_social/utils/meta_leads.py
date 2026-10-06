"""Parsing helpers for Meta (Facebook / Instagram) Lead Ads payloads.

Pure functions with no Frappe imports so they can be unit-tested anywhere.
"""

# Meta lead form field name -> ERPNext Lead field
FIELD_MAP = {
	"first_name": "first_name",
	"last_name": "last_name",
	"email": "email_id",
	"phone_number": "mobile_no",
	"company_name": "company_name",
	"job_title": "job_title",
	"city": "city",
	"state": "state",
	"website": "website",
	# `country` is deliberately absent: Lead.country is a Link, and free-text answers
	# that don't match a Country record would fail link validation.
}


def extract_leadgen_changes(payload: dict) -> list[dict]:
	"""Return one dict per `leadgen` change in a Page webhook delivery.

	Meta batches changes: {"object": "page", "entry": [{"id": page_id, "changes": [...]}]}.
	"""
	if not isinstance(payload, dict) or payload.get("object") != "page":
		return []
	events = []
	for entry in payload.get("entry") or []:
		page_id = str(entry.get("id") or "")
		for change in entry.get("changes") or []:
			if change.get("field") != "leadgen":
				continue
			value = change.get("value") or {}
			leadgen_id = str(value.get("leadgen_id") or "")
			if not leadgen_id:
				continue
			events.append(
				{
					"page_id": str(value.get("page_id") or page_id),
					"leadgen_id": leadgen_id,
					"form_id": str(value.get("form_id") or ""),
					"ad_id": str(value.get("ad_id") or ""),
					"created_time": value.get("created_time"),
					"raw": value,
				}
			)
	return events


def map_field_data(field_data: list[dict]) -> dict:
	"""Map a Graph API lead's `field_data` list onto ERPNext Lead fields.

	`field_data` looks like [{"name": "email", "values": ["a@b.com"]}, ...].
	A `full_name` answer is split into first/last name when those aren't given separately.
	"""
	answers = {}
	for item in field_data or []:
		name = (item.get("name") or "").strip().lower()
		values = [str(v).strip() for v in item.get("values") or [] if str(v).strip()]
		if name and values:
			answers[name] = ", ".join(values)

	lead = {FIELD_MAP[key]: value for key, value in answers.items() if key in FIELD_MAP}

	full_name = answers.get("full_name")
	if full_name and not lead.get("first_name"):
		first, _, last = full_name.partition(" ")
		lead["first_name"] = first
		if last and not lead.get("last_name"):
			lead["last_name"] = last.strip()

	return lead
