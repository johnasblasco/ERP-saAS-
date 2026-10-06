"""Parsing helpers for Meta (Facebook / Instagram) webhook payloads.

Pure functions with no Frappe imports so they can be unit-tested anywhere.
"""

from erp_social.utils.lead_fields import map_answers


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


def extract_messages(payload: dict) -> list[dict]:
	"""Return incoming Messenger / Instagram DMs from a webhook delivery.

	Messenger: {"object": "page", "entry": [{"id": page_id, "messaging": [...]}]}
	Instagram: {"object": "instagram", "entry": [{"id": ig_account_id, "messaging": [...]}]}
	Echoes of our own sends, reads and deliveries are skipped.
	"""
	if not isinstance(payload, dict):
		return []
	platform = {"page": "Facebook", "instagram": "Instagram"}.get(payload.get("object"))
	if not platform:
		return []

	messages = []
	for entry in payload.get("entry") or []:
		account_id = str(entry.get("id") or "")
		for item in entry.get("messaging") or []:
			message = item.get("message") or {}
			if not message or message.get("is_echo") or message.get("is_deleted"):
				continue
			mid = str(message.get("mid") or "")
			sender_id = str((item.get("sender") or {}).get("id") or "")
			if not mid or not sender_id or sender_id == account_id:
				continue
			attachments = [
				(a.get("payload") or {}).get("url")
				for a in message.get("attachments") or []
				if (a.get("payload") or {}).get("url")
			]
			messages.append(
				{
					"platform": platform,
					"account_id": account_id,
					"sender_id": sender_id,
					"mid": mid,
					"text": str(message.get("text") or ""),
					"attachments": attachments,
					"timestamp": item.get("timestamp"),
				}
			)
	return messages


def entry_ids(payload: dict) -> list[str]:
	"""Page / Instagram account IDs a delivery is about (used for routing)."""
	if not isinstance(payload, dict):
		return []
	return [str(e.get("id")) for e in payload.get("entry") or [] if isinstance(e, dict) and e.get("id")]


def map_field_data(field_data: list[dict]) -> dict:
	"""Map a Graph API lead's `field_data` list onto ERPNext Lead fields.

	`field_data` looks like [{"name": "email", "values": ["a@b.com"]}, ...].
	"""
	answers = {}
	for item in field_data or []:
		values = [str(v).strip() for v in item.get("values") or [] if str(v).strip()]
		if item.get("name") and values:
			answers[item["name"]] = ", ".join(values)
	return map_answers(answers)
