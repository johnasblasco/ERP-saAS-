# Architecture

## Stack

| Layer | Choice |
|---|---|
| Framework | Frappe v16 (Python 3.14, Node 24, MariaDB 11.8, Redis) |
| ERP | ERPNext v16: accounting, stock, buying, selling, CRM (`Lead`, `Opportunity`) |
| Our code | Three Frappe apps in `apps/` |
| Hosting | One bench in Docker (`deploy/`), Caddy for HTTPS |

## Apps

| App | Installed on | Job |
|---|---|---|
| `saas_control` | the operator's **control site** only | plans, tenants, signup, provisioning, billing, Meta webhook router, OAuth relay, TLS allow-list |
| `saas_tenant` | every **tenant site** | plan state, user limit, suspension, usage reporting |
| `erp_social` | every **tenant site** (also works standalone) | Facebook / Instagram / TikTok leads, Messenger + Instagram DMs, ad audiences |

No app imports another. Control and tenants talk over HTTP with a per-tenant key
(`saas_tenant_key` in the tenant's site_config, encrypted on the Tenant record).

## Tenancy: one site per customer

```
                 *.erp.example.com  ──►  Caddy (on-demand TLS) ──► nginx (route by Host) ──► one bench
                                                                                          ├── admin.example.com   (saas_control)
                                                                                          ├── acme.erp.example.com (erp_social, saas_tenant)
                                                                                          └── ...
```

- Each tenant is a Frappe **site**: its own MariaDB database, files and `site_config.json`.
- Requests are routed by Host header (`dns_multitenant`), so adding a tenant needs no proxy change.
- Caddy asks `saas_control.api.tls.allowed` before issuing a certificate, so only real sites get one.
- Every site runs the same app versions; `bench migrate` upgrades them all.

## Tenant lifecycle (`saas_control`)

```
/signup ──► Tenant "Pending Verification" ──email link──► "Queued" ──worker──► "Provisioning"
   new-site · install erpnext, erp_social, saas_tenant · set host_name / saas_control_url / saas_tenant_key
   · saas_tenant.setup.initialize (plan + owner user) ──► "Trial" or "Active"
   ──► ERPNext Customer + Subscription (paid plans) ──► "workspace ready" email with set-password link
```

- Provisioning runs the Frappe CLI (`python -m frappe.utils.bench_helper frappe ...`) in a long-queue
  worker. The MariaDB root password comes from `common_site_config.json`, never the command line.
  Keys and set-password links are masked in the stored log.
- A failed run can be retried; a leftover site is dropped only if the tenant was never live.
- **Billing** uses ERPNext on the control site: each paid SaaS Plan has a Subscription Plan, each
  tenant a Customer + Subscription. ERPNext raises the invoices; the daily job maps Subscription
  status onto the tenant (Trialing → Trial, Grace Period → Past Due, Unpaid/Cancelled → Suspended)
  and pushes it to the tenant site. Manual suspensions are never lifted automatically.
- **Suspended** tenants: `/api` calls are refused (403) except social webhooks and control-plane
  calls, so leads keep arriving; the desk shows a notice. Plan user limits are enforced on User save.
- **Archive** backs the site up, drops it, cancels billing and releases its social routes.

## Social integrations (`erp_social`)

```
Meta app webhook ─► control router (verify signature) ─► tenant(s) that registered the Page/IG id
                                                        ─► erp_social.api.webhooks.meta (verify again)
TikTok LEAD subscription ─► tenant's own URL with ?token=<per-site secret>
        │
        ▼
Social Lead Event (Received, raw payload; one per external id)  ──enqueue──►
   leadgen      → Graph API GET /{leadgen_id} → Lead (reused if the email exists)
   tiktok_lead  → answers are in the webhook → Lead
   message      → Social Contact (profile lookup) → Lead (optional) → Communication on the Lead
        │
        └─ Processed / Failed (traceback without tokens, Retry button)
```

- **Connect flows** ("Social Connect" page): OAuth with a single-use, user-bound state. Redirect URIs
  must be exact, so with a shared app the browser goes through the control site's relay, which only
  forwards to registered live tenants. Tokens are parked server-side for 30 minutes while the user
  picks Pages / ad accounts; they never reach the browser.
- **Routing**: on account changes the tenant posts its Page and Instagram IDs to the control site.
  An ID can belong to one live tenant; archived tenants release theirs.
- **Replies**: from the Lead form, through the Page (`/{page-id}/messages`), within Meta's 24-hour window.
- **Audiences**: Customers and/or Leads are normalised and SHA-256 hashed on the site, then sent to a
  Meta Custom Audience (email + phone) or a TikTok Custom Audience (email file, `REPLACE` on resync).
- **Standalone mode**: without `saas_control_url` in site_config, a site receives webhooks and OAuth
  callbacks at its own URLs using the app in Social Integration Settings.

### Platform API references

- Meta Graph API **v26.0** (configurable): leads, Page subscriptions, Messenger / Instagram
  messaging, Custom Audiences.
- TikTok API for Business **v1.3**: `oauth2/access_token`, `oauth2/advertiser/get`,
  `subscription/subscribe` (entity `LEAD`), `dmp/custom_audience/*`. Field names follow TikTok's
  official SDK specs; the lead webhook shape follows the `LEAD` subscription entity
  (`entry[].changes[{field, value}]`). TikTok lead webhooks are not signed, hence the URL token.
