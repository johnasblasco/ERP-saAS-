frappe.ui.form.on("Tenant", {
	refresh(frm) {
		if (frm.is_new()) return;
		const status = frm.doc.status;
		const action = (label, method, args, group) =>
			frm.add_custom_button(
				__(label),
				() =>
					frm.call(method, args).then(() => {
						frappe.show_alert({ message: __("Done"), indicator: "green" });
						frm.reload_doc();
					}),
				group && __(group)
			);

		if (frm.doc.site_url && ["Trial", "Active", "Past Due", "Suspended"].includes(status)) {
			frm.add_custom_button(__("Open Site"), () => window.open(frm.doc.site_url, "_blank"));
		}
		if (["Pending Verification", "Failed"].includes(status)) action("Provision", "provision");
		if (status === "Provisioning" && frm.doc.modified < frappe.datetime.add_minutes(frappe.datetime.now_datetime(), -60)) {
			action("Retry Provisioning", "provision");
		}
		if (["Trial", "Active", "Past Due"].includes(status)) action("Suspend", "suspend", null, "Actions");
		if (status === "Suspended") action("Resume", "resume", null, "Actions");
		if (["Trial", "Active", "Past Due"].includes(status)) action("Send Setup Link", "send_setup_link", null, "Actions");
		if (["Trial", "Active", "Past Due", "Suspended"].includes(status)) action("Sync Usage", "sync_now", null, "Actions");
		if (["Trial", "Active", "Past Due", "Suspended", "Failed"].includes(status)) {
			frm.add_custom_button(
				__("Archive"),
				() =>
					frappe.prompt(
						{
							fieldname: "confirm_subdomain",
							fieldtype: "Data",
							label: __("Type {0} to back up and delete this site", [frm.doc.subdomain]),
							reqd: 1,
						},
						({ confirm_subdomain }) =>
							frm.call("archive", { confirm_subdomain }).then(() => {
								frappe.show_alert({ message: __("Archiving started"), indicator: "orange" });
							}),
						__("Archive tenant"),
						__("Archive")
					),
				__("Actions")
			);
		}
		if (["Queued", "Provisioning"].includes(status)) {
			frm.dashboard.set_headline(__("Provisioning… this page refreshes automatically."));
			setTimeout(() => frm.reload_doc(), 5000);
		}
	},
});
