import frappe
from frappe import _
from frappe.model.document import Document

from erp_social.integrations.config import meta_client, tiktok_client, tiktok_webhook_url
from erp_social.integrations.meta_api import MetaAPIError
from erp_social.integrations.tiktok_api import TikTokAPIError
from erp_social.social_integration.routes import enqueue_route_sync

ROUTED_FIELDS = ("enabled", "platform", "external_id", "instagram_account_id")


class SocialPlatformAccount(Document):
	def validate(self):
		self.external_id = (self.external_id or "").strip()
		self.instagram_account_id = (self.instagram_account_id or "").strip()
		self.ad_account_id = (self.ad_account_id or "").strip().removeprefix("act_")
		if self.enabled:
			self.validate_unique("external_id", self.external_id, _("Page / Advertiser ID"))
			self.validate_unique("instagram_account_id", self.instagram_account_id, _("Instagram Account ID"))

	def validate_unique(self, fieldname, value, label):
		# Webhook deliveries are routed by these IDs, so each must map to one enabled account.
		if not value:
			return
		duplicate = frappe.db.exists(
			"Social Platform Account", {fieldname: value, "enabled": 1, "name": ("!=", self.name)}
		)
		if duplicate:
			frappe.throw(
				_("Enabled account {0} already uses {1} {2}.").format(
					frappe.bold(duplicate), label, frappe.bold(value)
				),
				title=_("Duplicate ID"),
			)

	def on_update(self):
		before = self.get_doc_before_save()
		if not before or any(before.get(f) != self.get(f) for f in ROUTED_FIELDS):
			enqueue_route_sync()

	def on_trash(self):
		if self.platform == "TikTok" and self.tiktok_subscription_id:
			try:
				tiktok_client().unsubscribe(self.tiktok_subscription_id)
			except TikTokAPIError, frappe.ValidationError:
				pass  # deleting the account locally must not depend on TikTok being reachable
		enqueue_route_sync()

	@frappe.whitelist()
	def subscribe_webhooks(self):
		self.check_permission("write")
		token = self.get_password("access_token", raise_exception=False)
		if not token:
			frappe.throw(_("Add an Access Token first."))
		try:
			if self.platform == "TikTok":
				self.tiktok_subscription_id = tiktok_client().subscribe_leads(
					self.external_id, token, tiktok_webhook_url()
				)
			else:
				meta_client(self).subscribe_page(self.external_id, token)
		except (MetaAPIError, TikTokAPIError) as e:
			frappe.throw(str(e), title=_("Could not subscribe"))
		self.webhook_subscribed = 1
		self.save()
		return True
