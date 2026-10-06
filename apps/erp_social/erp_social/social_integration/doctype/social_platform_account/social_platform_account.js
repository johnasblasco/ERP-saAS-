frappe.ui.form.on("Social Platform Account", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Subscribe webhooks"), () =>
			frm.call("subscribe_webhooks").then(() => {
				frappe.show_alert({ message: __("Webhooks subscribed"), indicator: "green" });
				frm.reload_doc();
			})
		);
		if (!frm.doc.webhook_subscribed) {
			frm.set_intro(
				__("This account isn't receiving webhooks yet. Use Subscribe webhooks, or reconnect it from {0}.", [
					`<a href="/desk/social-connect">${__("Social Connect")}</a>`,
				]),
				"orange"
			);
		}
	},
});
