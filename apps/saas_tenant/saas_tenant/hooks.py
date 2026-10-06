app_name = "saas_tenant"
app_title = "SaaS Tenant"
app_publisher = "johnasblasco"
app_description = "Tenant-side agent for the ERP SaaS: plan limits, suspension, usage reporting"
app_email = "johnaslblasco@gmail.com"
app_license = "mit"

required_apps = ["frappe"]

before_request = ["saas_tenant.guard.before_request"]
extend_bootinfo = ["saas_tenant.guard.extend_bootinfo"]
app_include_js = ["/assets/saas_tenant/js/saas_tenant.js"]

doc_events = {
	"User": {"validate": "saas_tenant.limits.validate_user_limit"},
}
