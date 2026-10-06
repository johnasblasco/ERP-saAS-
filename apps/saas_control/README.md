# SaaS Control

The control plane for the ERP SaaS. Install it on **one** site (the operator's admin site), never on
tenant sites.

- **SaaS Plan**: price, billing interval, user limit, signup-page copy. Paid plans get an ERPNext
  Subscription Plan automatically.
- **Tenant**: one customer workspace = one Frappe site (`<subdomain>.<root domain>`). Actions: Provision,
  Suspend, Resume, Sync Usage, Archive (backs up, then drops the site).
- **Signup** at `/signup` (also the home page): pick a plan and subdomain, confirm by email, the site is
  created in the background and the owner gets a set-password link.
- **Billing** with ERPNext Subscriptions on this site; the daily job mirrors Subscription status onto
  tenants (Grace Period -> Past Due, Unpaid/Cancelled -> Suspended).
- **Meta webhook router** (`/api/method/saas_control.api.router.meta`) and **OAuth relay**
  (`saas_control.api.relay.meta_oauth` / `tiktok_oauth`) for the shared Meta/TikTok apps.

Configuration lives in **SaaS Settings** and in `common_site_config.json` (`root_password`,
`erp_social_meta_app_secret`, `erp_social_meta_verify_token`, ...). See `docs/deployment.md`.
