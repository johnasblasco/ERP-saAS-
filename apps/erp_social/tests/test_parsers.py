from erp_social.utils.audience import meta_rows, normalize_email, normalize_phone, sha256, tiktok_email_file
from erp_social.utils.lead_fields import map_answers
from erp_social.utils.meta_leads import entry_ids, extract_messages
from erp_social.utils.tiktok_leads import extract_leads, map_lead


def test_map_answers_aliases_and_full_name():
	assert map_answers(
		{"Full Name": "Ana Maria Reyes", "Work Email": "a@x.com", "Phone Number": "+63 917"}
	) == {
		"first_name": "Ana",
		"last_name": "Maria Reyes",
		"email_id": "a@x.com",
		"mobile_no": "+63 917",
	}


def test_map_answers_email_address_alias():
	lead = map_answers({"Email Address": "a@x.com", "Company": "Acme", "Country": "PH"})
	assert lead == {"email_id": "a@x.com", "company_name": "Acme"}


def test_extract_messages_messenger_and_instagram():
	payload = {
		"object": "page",
		"entry": [
			{
				"id": "page",
				"messaging": [
					{
						"sender": {"id": "u1"},
						"timestamp": 5,
						"message": {
							"mid": "m1",
							"text": "hi",
							"attachments": [{"payload": {"url": "https://img"}}],
						},
					},
					{"sender": {"id": "page"}, "message": {"mid": "m2", "text": "echo", "is_echo": True}},
					{"sender": {"id": "u1"}, "read": {"watermark": 1}},
					{"sender": {"id": "u1"}, "message": {"mid": "m3", "is_deleted": True}},
				],
			}
		],
	}
	(msg,) = extract_messages(payload)
	assert msg == {
		"platform": "Facebook",
		"account_id": "page",
		"sender_id": "u1",
		"mid": "m1",
		"text": "hi",
		"attachments": ["https://img"],
		"timestamp": 5,
	}
	assert extract_messages({**payload, "object": "instagram"})[0]["platform"] == "Instagram"
	assert extract_messages({**payload, "object": "whatsapp_business_account"}) == []
	assert entry_ids(payload) == ["page"]


def test_extract_tiktok_leads():
	payload = {
		"object": 1,
		"entry": [
			{
				"id": "L1",
				"advertiser_id": 77,
				"changes": [
					{"field": "name", "value": "Juan Luna"},
					{"field": "phone_number", "value": "+639"},
				],
			},
			{"advertiser_id": 77},
		],
	}
	(lead,) = extract_leads(payload)
	assert (lead["lead_id"], lead["advertiser_id"]) == ("L1", "77")
	assert map_lead(lead) == {"first_name": "Juan", "last_name": "Luna", "mobile_no": "+639"}
	assert extract_leads({"object": 2, "entry": payload["entry"]}) == []


def test_normalize_phone():
	assert normalize_phone("+63 917-123-4567") == "639171234567"
	assert normalize_phone("0063 917 123 4567") == "639171234567"
	assert normalize_phone("0917 123 4567", "63") == "639171234567"
	assert normalize_phone("639171234567", "63") == "639171234567"
	assert normalize_phone("12345") is None
	assert normalize_phone(None) is None


def test_meta_rows_hash_and_dedupe():
	rows = meta_rows(
		[{"email": " A@X.com "}, {"email": "a@x.com"}, {"phone": "+1 415 555 0100"}, {"email": "bad"}]
	)
	assert rows == [[sha256("a@x.com"), ""], ["", sha256("14155550100")]]
	assert normalize_email("bad") is None


def test_tiktok_email_file():
	content = tiktok_email_file(
		[{"email": "b@x.com"}, {"email": "A@x.com"}, {"email": "b@x.com"}, {"phone": "1"}]
	)
	assert content.decode().split("\n") == sorted([sha256("a@x.com"), sha256("b@x.com")])
	assert tiktok_email_file([]) == b""
