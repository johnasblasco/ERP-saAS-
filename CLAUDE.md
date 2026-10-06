# ERP SaaS

Multi-tenant ERP SaaS on **Frappe Framework v16 + ERPNext v16**. Each customer is one Frappe site.
Social platforms (Facebook, Instagram, TikTok) feed ERPNext CRM.

## Layout

- `apps/saas_control/` runs on the **control site only**. It covers plans, tenants, signup (`www/signup.html`), provisioning through the Frappe CLI, ERPNext Subscription billing, the Meta webhook router, the OAuth relay, and the TLS allow-list.
- `apps/saas_tenant/` runs on **every tenant site**. It covers plan state, user limits, suspension and the usage API.
- `apps/erp_social/` runs on **every tenant site** and covers OAuth connect, lead and DM webhooks, replies, and audiences.
  - It works standalone too.
  - Pure parsers and API clients live in `utils/` and `integrations/*_api.py`.
- `scripts/setup-bench.sh` builds a dev bench with `control.localhost` and `erp.localhost`. `scripts/ci-test.sh` runs every integration suite.
- `deploy/` holds the production image, the compose stack and the Caddyfile. `.devcontainer/` holds the dev stack.
- `docs/architecture.md` explains how it fits together; read it before structural changes. `docs/deployment.md` covers production setup.
- `.claude/skills/` holds the vendored `frappe-*` skills (don't edit them; see FRAPPE_SKILLS_NOTICE.md), plus `frontend-design` and `webapp-testing`.

## Rules

- Never modify Frappe or ERPNext source. Extend them through our apps.
- The apps never import each other. Control and tenants talk over HTTP with the tenant key.
- Tenancy is **one Frappe site per customer**. There are no tenant ID columns.
- Secrets live in `Password` fields or site config, never in code, logs, error messages or fixtures.
  - API clients raise errors without tokens, and outside `except` blocks so tracebacks don't chain them.
- Public (`allow_guest=True`) endpoints verify a signature, token or tenant key before touching data.
- Webhook handlers log the event, enqueue the work, and return 200 fast.
- Pure helpers have no `frappe` import, so they unit-test without a bench.
- v16 specifics:
  - The desk lives at `/desk/...`.
  - `frappe.sendmail` raises without an Email Account.
  - `bench execute` prints return values as JSON.
  - Never run `bench build --apps <ours>`, because it empties assets.json.
- Code style: tabs, ruff (config in each app's `pyproject.toml`), line length 110.

## Commands

```bash
ruff check apps && ruff format --check apps
(cd apps/erp_social && uv run --no-project --with pytest --with requests python -m pytest -q tests)
(cd apps/saas_control && uv run --no-project --with pytest python -m pytest -q tests)

# inside a bench (scripts/setup-bench.sh)
bench --site erp.localhost run-tests --app erp_social
bench --site erp.localhost run-tests --app saas_tenant
bench --site control.localhost run-tests --app saas_control
bench --site <site> migrate   # after changing DocType JSON
```

## Workflow

Research, then plan, then implement.

- For anything that touches more than one app or a DocType schema, plan first in plan mode, and check the `frappe-agent-architect` skill.
- Run the `frappe-agent-validator` skill on new Frappe code.
- For UI work, use `frontend-design`, and check the real page in a browser with `webapp-testing`.
