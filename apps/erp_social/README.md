# ERP Social

Frappe app that captures leads from Facebook, Instagram and TikTok into ERPNext CRM.

## Set up a Facebook / Instagram page

1. In ERPNext, create a **Social Platform Account**: platform `Facebook`, the Page ID, your Meta App Secret,
   a random Verify Token, and a long-lived Page access token with `leads_retrieval`.
2. The form shows the callback URL. In the Meta App dashboard → Webhooks → Page, subscribe to `leadgen`
   with that URL and the same Verify Token.
3. Subscribe the app to the Page (`POST /{page-id}/subscribed_apps?subscribed_fields=leadgen`).

New leads appear as **Social Lead Event** records and become ERPNext **Leads**. Failed events show the
error and a **Retry** button.

## Tests

```bash
uv run --no-project --with pytest python -m pytest -q tests      # pure unit tests
bench --site <site> run-tests --app erp_social                    # integration tests
```
