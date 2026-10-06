"""Parsing helpers for TikTok lead webhooks. No Frappe imports.

TikTok posts {"request_id", "object": 1, "time", "entry": [lead, ...]} where each lead is
{"id", "lead_source", "page_id", "advertiser_id", "campaign_name", "ad_name", "create_time",
 "changes": [{"field": "...", "value": "..."}]}  (object 1 = LEAD).
"""

from erp_social.utils.lead_fields import map_answers

LEAD_OBJECT = 1


def extract_leads(payload: dict) -> list[dict]:
	if not isinstance(payload, dict) or str(payload.get("object")) != str(LEAD_OBJECT):
		return []
	leads = []
	for entry in payload.get("entry") or []:
		if not isinstance(entry, dict) or not entry.get("id"):
			continue
		answers = {
			c.get("field"): c.get("value")
			for c in entry.get("changes") or []
			if isinstance(c, dict) and c.get("field")
		}
		leads.append(
			{
				"lead_id": str(entry["id"]),
				"advertiser_id": str(entry.get("advertiser_id") or ""),
				"page_id": str(entry.get("page_id") or ""),
				"lead_source": entry.get("lead_source") or "",
				"campaign_name": entry.get("campaign_name") or "",
				"ad_name": entry.get("ad_name") or "",
				"answers": answers,
				"raw": entry,
			}
		)
	return leads


def map_lead(lead: dict) -> dict:
	return map_answers(lead.get("answers") or {})
