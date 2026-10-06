frappe.ui.form.on("Social Audience", {
	refresh(frm) {
		if (frm.is_new() || !frm.has_perm("write")) return;
		frm.add_custom_button(__("Sync now"), () =>
			frm.call("sync_now").then(() => {
				frappe.show_alert({ message: __("Sync started"), indicator: "blue" });
				setTimeout(() => frm.reload_doc(), 3000);
			})
		);
	},
});
