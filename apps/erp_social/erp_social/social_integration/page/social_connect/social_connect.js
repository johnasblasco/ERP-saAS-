// Connect Facebook Pages (with their Instagram accounts) and TikTok ad accounts, and see whether
// each one is delivering leads. The OAuth callbacks land back here with ?pending=<key>.
frappe.pages["social-connect"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Social Connect"), single_column: true });
	new SocialConnect(page);
};

class SocialConnect {
	constructor(page) {
		this.page = page;
		this.$body = $(`<div class="social-connect"></div>`).appendTo(page.main);
		this.inject_style();
		this.page.set_secondary_action(__("Refresh"), () => this.render());
		this.render().then(() => this.handle_return());
	}

	async render() {
		const data = await frappe.xcall("erp_social.api.oauth.overview");
		this.data = data;
		const is_admin = frappe.user.has_role("System Manager");
		const esc = frappe.utils.escape_html;

		const platform_row = (key, title, description, ready) => `
			<div class="sc-platform">
				<div>
					<div class="sc-platform-title">${title}</div>
					<div class="text-muted">${description}</div>
					${ready ? "" : `<div class="sc-hint">${
						data.managed
							? __("Your provider hasn't enabled this yet.")
							: __("Add the app credentials in {0} first.", [
									`<a href="/desk/social-integration-settings">${__("Social Integration Settings")}</a>`,
							  ])
					}</div>`}
				</div>
				${is_admin ? `<button class="btn btn-primary btn-sm" data-connect="${key}" ${ready ? "" : "disabled"}>${__("Connect")}</button>` : ""}
			</div>`;

		const rows = data.accounts
			.map((a) => {
				const where = a.platform === "TikTok" ? __("TikTok ads") : a.instagram_username
					? __("Facebook Page + Instagram @{0}", [esc(a.instagram_username)])
					: __("Facebook Page");
				const state = !a.enabled
					? `<span class="indicator-pill gray">${__("Off")}</span>`
					: a.webhook_subscribed
					? `<span class="indicator-pill green">${__("Receiving")}</span>`
					: `<span class="indicator-pill orange">${__("Not receiving")}</span>`;
				const failed = a.failed
					? `<a href="/desk/social-lead-event?account=${encodeURIComponent(a.name)}&status=Failed" class="text-danger">${__("{0} failed", [a.failed])}</a>`
					: "";
				return `<tr>
					<td><a href="/desk/social-platform-account/${encodeURIComponent(a.name)}">${esc(a.name)}</a><div class="text-muted small">${where}</div></td>
					<td>${state}</td>
					<td class="text-right">${a.processed}</td>
					<td class="text-right">${failed}</td>
				</tr>`;
			})
			.join("");

		this.$body.html(`
			<div id="sc-alert"></div>
			<section class="sc-section">
				<h4>${__("Connect an account")}</h4>
				${platform_row(
					"meta",
					__("Facebook & Instagram"),
					__("Lead ads from your Page and its Instagram account become Leads. Messenger and Instagram chats appear on the Lead."),
					data.meta_ready
				)}
				${platform_row(
					"tiktok",
					__("TikTok"),
					__("Instant form leads from your TikTok ad accounts become Leads."),
					data.tiktok_ready
				)}
			</section>
			<section class="sc-section">
				<h4>${__("Connected accounts")}</h4>
				${
					rows
						? `<table class="table sc-table">
							<thead><tr><th>${__("Account")}</th><th>${__("Webhooks")}</th><th class="text-right">${__("Leads & messages")}</th><th class="text-right">${__("Problems")}</th></tr></thead>
							<tbody>${rows}</tbody></table>`
						: `<p class="text-muted">${__("Nothing connected yet. Connect a Facebook Page or TikTok ad account above to start receiving leads.")}</p>`
				}
			</section>
			${
				!data.managed && is_admin
					? `<section class="sc-section">
						<h4>${__("App setup")}</h4>
						<p class="text-muted">${__("Enter these in your Meta and TikTok developer apps.")}</p>
						<dl class="sc-urls">
							<dt>${__("Meta webhook callback URL")}</dt><dd><code>${esc(data.meta_webhook_url)}</code></dd>
							<dt>${__("Meta OAuth redirect URI")}</dt><dd><code>${esc(data.meta_redirect_uri)}</code></dd>
							<dt>${__("TikTok redirect URI")}</dt><dd><code>${esc(data.tiktok_redirect_uri)}</code></dd>
						</dl>
					</section>`
					: ""
			}
		`);

		this.$body.find("[data-connect]").on("click", (e) => this.start($(e.currentTarget).data("connect")));
	}

	async start(platform) {
		const method = platform === "meta" ? "meta_login_url" : "tiktok_login_url";
		const url = await frappe.xcall(`erp_social.api.oauth.${method}`);
		window.location.href = url;
	}

	handle_return() {
		const params = new URLSearchParams(window.location.search);
		const clean = () => window.history.replaceState(null, "", "/desk/social-connect");
		if (params.get("error")) {
			this.alert(params.get("error"), "red");
			clean();
		} else if (params.get("pending")) {
			const key = params.get("pending");
			clean();
			params.get("platform") === "tiktok" ? this.pick_tiktok(key) : this.pick_meta(key);
		}
	}

	alert(message, color) {
		this.$body.find("#sc-alert").html(
			`<div class="alert alert-${color === "red" ? "danger" : "success"}">${frappe.utils.escape_html(message)}</div>`
		);
	}

	async pick_meta(key) {
		const { pages, ad_accounts } = await frappe.xcall("erp_social.api.oauth.meta_pending", { key });
		if (!pages.length) {
			return this.alert(__("Facebook didn't share any Pages. Reconnect and select at least one Page."), "red");
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Choose Pages to connect"),
			fields: [
				{
					fieldtype: "MultiCheck",
					fieldname: "page_ids",
					label: __("Pages"),
					reqd: 1,
					options: pages.map((p) => ({
						label: p.instagram_username ? `${p.name} (Instagram @${p.instagram_username})` : p.name,
						value: p.id,
						checked: !p.connected,
					})),
				},
				{
					fieldtype: "Select",
					fieldname: "ad_account_id",
					label: __("Ad account for audiences"),
					description: __("Optional. Used to send customer lists to Facebook as Custom Audiences."),
					options: [{ label: __("None"), value: "" }].concat(
						ad_accounts.map((a) => ({ label: `${a.name} (${a.id})`, value: a.id }))
					),
				},
			],
			primary_action_label: __("Connect"),
			primary_action: (values) => this.connect("meta_connect", { key, ...values }, dialog),
		});
		dialog.show();
	}

	async pick_tiktok(key) {
		const { advertisers } = await frappe.xcall("erp_social.api.oauth.tiktok_pending", { key });
		const dialog = new frappe.ui.Dialog({
			title: __("Choose TikTok ad accounts"),
			fields: [
				{
					fieldtype: "MultiCheck",
					fieldname: "advertiser_ids",
					label: __("Ad accounts"),
					reqd: 1,
					options: advertisers.map((a) => ({ label: `${a.name} (${a.id})`, value: a.id, checked: !a.connected })),
				},
			],
			primary_action_label: __("Connect"),
			primary_action: (values) => this.connect("tiktok_connect", { key, ...values }, dialog),
		});
		dialog.show();
	}

	async connect(method, args, dialog) {
		dialog.disable_primary_action();
		try {
			const results = await frappe.xcall(`erp_social.api.oauth.${method}`, args);
			dialog.hide();
			const failed = results.filter((r) => !r.ok);
			if (failed.length) {
				this.alert(
					__("Connected, but these accounts aren't receiving webhooks yet: {0}", [
						failed.map((r) => `${r.account} (${r.error})`).join("; "),
					]),
					"red"
				);
			} else {
				frappe.show_alert({ message: __("Connected {0} account(s)", [results.length]), indicator: "green" });
			}
			await this.render();
		} finally {
			dialog.enable_primary_action();
		}
	}

	inject_style() {
		if (document.getElementById("social-connect-style")) return;
		$(`<style id="social-connect-style">
			.social-connect { max-width: 56rem; padding: var(--padding-md) var(--padding-lg); }
			.sc-section { margin-bottom: var(--margin-xl); }
			.sc-section h4 { font-size: var(--text-lg); font-weight: var(--weight-semibold); margin-bottom: var(--margin-sm); }
			.sc-platform { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--margin-md);
				padding: var(--padding-md) 0; border-bottom: 1px solid var(--border-color); }
			.sc-platform:first-of-type { border-top: 1px solid var(--border-color); }
			.sc-platform-title { font-weight: var(--weight-semibold); }
			.sc-hint { margin-top: var(--margin-xs); font-size: var(--text-sm); color: var(--text-muted); }
			.sc-table td { vertical-align: middle; }
			.sc-urls dt { font-weight: var(--weight-medium); margin-top: var(--margin-sm); }
			.sc-urls dd { margin: 0; word-break: break-all; }
		</style>`).appendTo("head");
	}
}
