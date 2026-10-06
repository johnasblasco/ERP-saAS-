# Deployment

Everything runs on one Docker host: one bench serving the control site and every tenant site.

## 1. DNS

Point both of these at the server:

- the control site, e.g. `admin.example.com`
- a wildcard for tenants, e.g. `*.erp.example.com`

## 2. Build the image

```bash
docker build -f deploy/Containerfile -t ghcr.io/<you>/erp-saas:$(git rev-parse --short HEAD) .
docker push ghcr.io/<you>/erp-saas:<tag>
```

The image is the official `frappe/erpnext` image plus `erp_social`, `saas_tenant` and `saas_control`.

## 3. Configure and start

```bash
cp deploy/.env.example deploy/.env      # set IMAGE, CONTROL_SITE, ACME_EMAIL, passwords, app keys
docker compose -f deploy/compose.yaml --env-file deploy/.env up -d
```

`create-control-site` creates the control site with ERPNext and `saas_control` on first start.
Caddy issues certificates on demand for the control site and live tenant sites only.

## 4. Set up the control site

Sign in at `https://<CONTROL_SITE>` as Administrator.

1. Finish the ERPNext setup wizard (your company, currency, fiscal year). Invoices come from this company.
2. **Email Account**: add an outgoing account. Signup verification and "workspace ready" emails need it.
   Without one, signups are paused with a clear message and provisioning records the problem on the Tenant.
3. **SaaS Settings**:
   - Root Domain `erp.example.com`, URL Scheme `https`.
   - Apps to Install `erpnext`, `erp_social`, `saas_tenant`.
   - Trial Days, Default Plan, Support Email.
   - Billing Company, for paid plans.
4. **SaaS Plan**: create your plans (price, users, features). Paid plans get an ERPNext Subscription Plan automatically.
5. For collecting payments, set up a Payment Gateway (e.g. Stripe through the `payments` app) on the
   Subscription Plans, or reconcile payments manually against the generated Sales Invoices.

The signup page is the control site's home page (`/signup`).

## 5. Social apps (optional, shared by all tenants)

### Meta (Facebook + Instagram)

In developers.facebook.com create a **Business** app with Facebook Login for Business, Webhooks,
Messenger and Instagram.

| Setting | Value |
|---|---|
| Valid OAuth Redirect URI | `https://<CONTROL_SITE>/api/method/saas_control.api.relay.meta_oauth` |
| Webhooks → Page → callback | `https://<CONTROL_SITE>/api/method/saas_control.api.router.meta` |
| Webhooks → Page → fields | `leadgen`, `messages` |
| Webhooks → Instagram → callback / fields | same URL, `messages` |
| Verify token | the value of `META_VERIFY_TOKEN` |

The app needs these permissions, which require App Review before customers outside your business can use them:
`pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`, `leads_retrieval`, `pages_messaging`,
`instagram_basic`, `instagram_manage_messages`, `ads_management`, `business_management`.

Put the App ID and secret in `META_APP_ID` / `META_APP_SECRET`, then restart the stack.

### TikTok

In business-api.tiktok.com create a Marketing API app with lead and audience scopes.

- Redirect URL: `https://<CONTROL_SITE>/api/method/saas_control.api.relay.tiktok_oauth`
- Put the App ID and secret in `TIKTOK_APP_ID` / `TIKTOK_APP_SECRET`.

Lead webhooks are registered per tenant automatically when a tenant connects an ad account.

## Operations

| Task | How |
|---|---|
| Upgrade | Build a new image, `docker compose up -d`, then `docker compose exec backend bench --site all migrate` |
| Backups | `docker compose exec backend bench --site all backup --with-files` (schedule it; copy `sites/*/private/backups` off the host) |
| A tenant is stuck | Tenant form: Provisioning Log and Last Error; **Retry Provisioning** after an hour in "Provisioning" |
| Suspend / resume | Tenant form → Actions |
| Owner lost the email | Tenant form → Actions → **Send Setup Link** |
| Remove a tenant | Tenant form → **Archive** (backs up, then drops the site) |
| Webhook delivery problems | Control site Error Log ("Meta webhook not delivered to …"); tenant: Social Lead Event list, status Failed |

## Self-hosted single company (no control plane)

Install only `erpnext` and `erp_social` on a site. Put the Meta and TikTok app credentials in
**Social Integration Settings**; the **Social Connect** page then shows the webhook and redirect URLs to
enter in your own Meta and TikTok apps.
