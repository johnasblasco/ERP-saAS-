// Reply to a Lead's Messenger / Instagram conversation from the Lead form.
frappe.ui.form.on("Lead", {
	async refresh(frm) {
		if (frm.is_new() || !frm.has_perm("write")) return;
		const contact = await frappe.db.get_value(
			"Social Contact",
			{ lead: frm.doc.name },
			["platform", "full_name"]
		);
		const { platform } = contact.message || {};
		if (!platform) return;

		frm.add_custom_button(__("Reply on {0}", [__(platform === "Instagram" ? "Instagram" : "Messenger")]), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Reply to {0}", [contact.message.full_name || frm.doc.lead_name]),
				fields: [
					{
						fieldname: "message",
						fieldtype: "Small Text",
						label: __("Message"),
						reqd: 1,
						description: __("Meta only delivers replies within 24 hours of the customer's last message."),
					},
				],
				primary_action_label: __("Send"),
				primary_action({ message }) {
					dialog.disable_primary_action();
					frappe
						.call({
							method: "erp_social.social_integration.messaging.send_reply",
							args: { lead: frm.doc.name, message },
						})
						.then(() => {
							dialog.hide();
							frappe.show_alert({ message: __("Sent"), indicator: "green" });
							frm.reload_doc();
						})
						.finally(() => dialog.enable_primary_action());
				},
			});
			dialog.show();
		});
	},
});
