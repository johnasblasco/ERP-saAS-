# Architecture

## Stack

| Layer | Choice |
|---|---|
| Framework | Frappe v16 (Python 3.14, Node 24, MariaDB 11.8, Redis) |
| ERP | ERPNext v16: accounting, stock, selling, buying, HR basics, CRM (`Lead`, `Opportunity`) |
| Our code | Custom Frappe apps in `apps/` |
| Hosting | Frappe Cloud, or self-hosted with `frappe/frappe_docker` |

## Tenancy: one site per customer

Each customer gets its own Frappe **site** (own database, files, `site_config.json`) on a shared bench.
Frappe routes requests by hostname (`acme.yourerp.com` → site `acme.yourerp.com`).

- Isolation comes from separate databases, not tenant columns.
- Every site runs the same app versions; `bench migrate` upgrades them all.
- Per-tenant secrets (Meta app secret, page tokens) are stored per site in `Password` fields.
- Provisioning a tenant = `bench new-site <host> --install-app erpnext --install-app erp_social` (later automated by a control-plane app or Frappe Cloud's Press API).

## Social integrations (`apps/erp_social`)

```
Facebook/Instagram Lead Ads ──POST──▶ /api/method/erp_social.api.webhooks.meta
TikTok                      ──POST──▶ /api/method/erp_social.api.webhooks.tiktok
        │  verify signature with the matching Social Platform Account's secret
        ▼
Social Lead Event (status Received, raw payload)   ← audit log, dedup by external_id
        │  frappe.enqueue (after commit)
        ▼
lead_sync.process_meta_lead_event
        │  Graph API GET /{leadgen_id} (access token + appsecret_proof)
        ▼
ERPNext Lead (reused if the email already exists) → event Processed / Failed (with retry button)
```

Each tenant site has its own webhook URL, so a delivery can only ever create data in that tenant.

### Status

| Platform | Webhook verify | Lead creation |
|---|---|---|
| Facebook Lead Ads | done | done |
| Instagram Lead Ads | done (same Page webhook as Facebook) | done |
| TikTok | signature verify + event log | TODO: map TikTok lead payload |

### Next steps

1. TikTok lead mapping once a TikTok Business lead form webhook is available to test against.
2. Messenger / Instagram DMs → ERPNext `Communication` linked to the Lead.
3. Outbound: push ERPNext `Customer` lists to Meta Custom Audiences.
4. Tenant onboarding: OAuth "Connect Facebook Page" flow instead of pasting tokens.
