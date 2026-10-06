"""Push ERPNext Customers / Leads to Meta and TikTok Custom Audiences (hashed client-side)."""

import frappe
from frappe import _
from frappe.utils import now_datetime

from erp_social.integrations.config import meta_client, tiktok_client
from erp_social.integrations.meta_api import MetaAPIError
from erp_social.integrations.tiktok_api import TikTokAPIError
from erp_social.utils.audience import meta_rows, tiktok_email_file

AUDIENCE = "Social Audience"


def sync_all_audiences():
	"""Daily scheduler job."""
	for name in frappe.get_all(AUDIENCE, filters={"auto_sync": 1}, pluck="name"):
		frappe.enqueue(
			sync_audience,
			audience_name=name,
			queue="long",
			job_id=f"erp_social::audience::{name}",
			deduplicate=True,
		)


def sync_audience(audience_name: str):
	frappe.set_user("Administrator")
	audience = frappe.get_doc(AUDIENCE, audience_name)
	audience.db_set({"status": "Syncing", "error": None})
	frappe.db.commit()  # make "Syncing" visible while the upload runs

	try:
		account = frappe.get_doc("Social Platform Account", audience.account)
		contacts = collect_contacts(audience)
		if account.platform == "TikTok":
			count = _sync_tiktok(audience, account, contacts)
		else:
			count = _sync_meta(audience, account, contacts)
	# No rollback on failure: the sync's only writes are this audience's own status fields.
	except (MetaAPIError, TikTokAPIError, frappe.ValidationError) as e:
		audience.db_set({"status": "Failed", "error": str(e)})
		return
	except Exception:
		audience.db_set({"status": "Failed", "error": frappe.get_traceback()})
		frappe.log_error(
			title=f"Audience sync {audience_name} failed",
			reference_doctype=AUDIENCE,
			reference_name=audience_name,
		)
		return

	audience.db_set({"status": "Synced", "last_synced_on": now_datetime(), "last_sync_count": count})


def collect_contacts(audience) -> list[dict]:
	contacts = []
	if audience.source in ("Customers", "Customers and Leads"):
		filters = {"disabled": 0}
		if audience.customer_group:
			groups = frappe.db.get_descendants("Customer Group", audience.customer_group) or []
			filters["customer_group"] = ("in", [audience.customer_group, *groups])
		for row in frappe.get_all("Customer", filters=filters, fields=["email_id", "mobile_no"]):
			contacts.append({"email": row.email_id, "phone": row.mobile_no})
	if audience.source in ("Leads", "Customers and Leads"):
		for row in frappe.get_all(
			"Lead", filters={"status": ("!=", "Do Not Contact")}, fields=["email_id", "mobile_no"]
		):
			contacts.append({"email": row.email_id, "phone": row.mobile_no})
	return contacts


def _sync_meta(audience, account, contacts) -> int:
	if not account.ad_account_id:
		frappe.throw(_("Set the Ad Account ID on {0}.").format(account.name))
	user_token = account.get_password("user_access_token", raise_exception=False)
	if not user_token:
		frappe.throw(
			_("{0} has no User Access Token. Reconnect it from Social Connect.").format(account.name)
		)

	client = meta_client(account)
	if not audience.audience_id:
		audience_id = client.create_custom_audience(
			account.ad_account_id, audience.audience_name, user_token, description=_("Synced from ERPNext")
		)
		audience.db_set("audience_id", audience_id)
		frappe.db.commit()  # never lose the ID of an audience that now exists on Meta
	rows = meta_rows(
		contacts, frappe.db.get_single_value("Social Integration Settings", "default_country_code")
	)
	if rows:
		client.add_audience_users(audience.audience_id, rows, user_token)
	return len(rows)


def _sync_tiktok(audience, account, contacts) -> int:
	token = account.get_password("access_token", raise_exception=False)
	if not token:
		frappe.throw(_("Account {0} has no Access Token.").format(account.name))
	content = tiktok_email_file(contacts)
	if not content:
		return 0

	client = tiktok_client()
	file_path = client.upload_audience_file(account.external_id, token, content, "EMAIL_SHA256")
	if audience.audience_id:
		# REPLACE keeps the audience equal to the current customer list (people who left drop out).
		client.update_audience(
			account.external_id, token, audience.audience_id, [file_path], action="REPLACE"
		)
	else:
		audience_id = client.create_audience(
			account.external_id, token, audience.audience_name, [file_path], "EMAIL_SHA256"
		)
		audience.db_set("audience_id", audience_id)
		frappe.db.commit()
	return content.count(b"\n") + 1
