app_name = "saas_control"
app_title = "SaaS Control"
app_publisher = "johnasblasco"
app_description = "SaaS control plane: plans, tenant provisioning, billing, webhook routing"
app_email = "johnaslblasco@gmail.com"
app_license = "mit"

# The control site runs ERPNext too: tenants are billed with ERPNext Subscriptions.
required_apps = ["frappe", "erpnext"]

# The control site's home page is the public pricing + signup page.
home_page = "signup"

scheduler_events = {
	"daily": ["saas_control.lifecycle.daily"],
}
