frappe.ui.form.on("Social Platform Account", {
	refresh(frm) {
		if (frm.is_new()) return;
		const path =
			frm.doc.platform === "TikTok"
				? "/api/method/erp_social.api.webhooks.tiktok"
				: "/api/method/erp_social.api.webhooks.meta";
		frm.set_intro(
			__("Webhook callback URL: {0}", [`<code>${frappe.urllib.get_base_url()}${path}</code>`]),
			"blue"
		);
	},
});
