app_name = "erp_social"
app_title = "ERP Social"
app_publisher = "johnasblasco"
app_description = "Capture leads from Facebook, Instagram and TikTok into ERPNext CRM"
app_email = "johnaslblasco@gmail.com"
app_license = "mit"

required_apps = ["frappe", "erpnext"]

doctype_js = {"Lead": "public/js/lead.js"}

scheduler_events = {
	"daily": ["erp_social.social_integration.audiences.sync_all_audiences"],
}
