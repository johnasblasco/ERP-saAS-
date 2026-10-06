# ERP Social

Connects a workspace to Facebook, Instagram and TikTok:

- Facebook and Instagram lead ads, and TikTok instant forms, become ERPNext Leads.
- Messenger and Instagram DMs appear on the Lead. You can reply from there with **Reply on Messenger** / **Reply on Instagram**.
- Customers and Leads sync to Meta and TikTok **Custom Audiences** (Social Audience), hashed on the site.

## Use it

Open **Social Connect** (Social workspace), then click **Connect** for Facebook & Instagram or TikTok:

1. Approve access on Facebook or TikTok.
2. Pick the Pages or ad accounts to connect.

Webhooks are subscribed for you. Incoming events are listed under **Social Lead Event**. Failed ones show the error and a **Retry** button.

## Configure

The platform apps come from **Social Integration Settings**. When a field there is blank, the site falls back to the bench-wide config keys `erp_social_meta_*` / `erp_social_tiktok_*`.

With a SaaS control plane (`saas_control_url` in site_config), Meta webhooks and OAuth redirects go through the control site. See `docs/architecture.md`.

## Tests

```bash
uv run --no-project --with pytest --with requests python -m pytest -q tests   # pure unit tests
bench --site <site> run-tests --app erp_social                               # integration tests
```
