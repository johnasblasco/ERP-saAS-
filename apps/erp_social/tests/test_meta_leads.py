from erp_social.utils.meta_leads import extract_leadgen_changes, map_field_data


def test_extract_leadgen_changes_keeps_only_leadgen():
	payload = {
		"object": "page",
		"entry": [
			{
				"id": "111",
				"changes": [
					{"field": "leadgen", "value": {"leadgen_id": 999, "form_id": "f1", "ad_id": "a1"}},
					{"field": "feed", "value": {"post_id": "x"}},
					{"field": "leadgen", "value": {}},
				],
			}
		],
	}
	events = extract_leadgen_changes(payload)
	assert len(events) == 1
	assert events[0]["page_id"] == "111"
	assert events[0]["leadgen_id"] == "999"
	assert events[0]["form_id"] == "f1"


def test_extract_ignores_non_page_payloads():
	assert extract_leadgen_changes({"object": "instagram", "entry": []}) == []
	assert extract_leadgen_changes([]) == []
	assert extract_leadgen_changes({}) == []


def test_map_field_data_maps_known_fields_and_splits_full_name():
	lead = map_field_data(
		[
			{"name": "full_name", "values": ["Juan Dela Cruz"]},
			{"name": "email", "values": ["juan@example.com"]},
			{"name": "phone_number", "values": ["+639171234567"]},
			{"name": "country", "values": ["PH"]},
			{"name": "favorite_color", "values": ["blue"]},
		]
	)
	assert lead == {
		"first_name": "Juan",
		"last_name": "Dela Cruz",
		"email_id": "juan@example.com",
		"mobile_no": "+639171234567",
	}


def test_map_field_data_prefers_explicit_names_and_skips_blanks():
	lead = map_field_data(
		[
			{"name": "First_Name", "values": ["Ana"]},
			{"name": "full_name", "values": ["Someone Else"]},
			{"name": "company_name", "values": ["  "]},
		]
	)
	assert lead == {"first_name": "Ana"}
