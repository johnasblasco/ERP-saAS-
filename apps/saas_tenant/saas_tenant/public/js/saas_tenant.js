// Plan notices in the desk: trial countdown, payment reminders, and a blocking notice when suspended.
$(document).on("startup", () => {
	const sub = frappe.boot.saas_subscription;
	if (!sub || !sub.status || sub.status === "Active") return;

	const contact = sub.support_email
		? `<a href="mailto:${encodeURIComponent(sub.support_email)}">${frappe.utils.escape_html(sub.support_email)}</a>`
		: __("your provider");

	if (sub.status === "Suspended") {
		frappe.msgprint({
			title: __("Workspace suspended"),
			message: __("Access to your data is paused until your subscription is settled. Contact {0} to restore it.", [contact]),
			indicator: "red",
		});
		return;
	}

	let message;
	if (sub.status === "Trial" && sub.trial_ends_on) {
		const days = frappe.datetime.get_day_diff(sub.trial_ends_on, frappe.datetime.get_today());
		message =
			days > 0
				? __("{0} days left in your trial of the {1} plan.", [days, frappe.utils.escape_html(sub.plan_name || "")])
				: __("Your trial ends today.");
	} else if (sub.status === "Past Due") {
		message = __("Your latest invoice is past due. Pay it to keep using your workspace, or contact {0}.", [contact]);
	}
	if (!message) return;

	const bar = $(`<div class="saas-tenant-notice" role="status"></div>`).html(message);
	bar.css({
		padding: "6px 16px",
		"font-size": "var(--text-sm)",
		"text-align": "center",
		background: sub.status === "Past Due" ? "var(--bg-orange)" : "var(--bg-blue)",
		color: sub.status === "Past Due" ? "var(--text-on-orange)" : "var(--text-on-blue)",
	});
	$("body").prepend(bar);
});
