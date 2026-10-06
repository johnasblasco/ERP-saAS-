frappe.listview_settings["Social Lead Event"] = {
	get_indicator(doc) {
		const colors = { Received: "blue", Processed: "green", Failed: "red", Ignored: "gray" };
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
	},
};
