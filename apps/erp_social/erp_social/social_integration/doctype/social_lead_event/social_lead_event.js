frappe.ui.form.on("Social Lead Event", {
	refresh(frm) {
		if (frm.doc.status === "Failed" && frm.has_perm("write")) {
			frm.add_custom_button(__("Retry"), () =>
				frm.call("retry").then(() => {
					frappe.show_alert({ message: __("Queued for retry"), indicator: "blue" });
					frm.reload_doc();
				})
			);
		}
	},
});
