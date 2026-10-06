# ERP SaaS

Multi-tenant ERP SaaS on **Frappe Framework v16 + ERPNext v16**, with custom apps that connect
ERPNext CRM to social platforms (Facebook, Instagram, TikTok, later more).

## Layout

- `apps/<app>/` — our Frappe apps. Each is a standalone Frappe app (own `pyproject.toml`, `hooks.py`).
  - `apps/erp_social/` — social lead capture: webhooks → `Social Lead Event` → ERPNext `Lead`.
- `scripts/setup-bench.sh` — builds a local bench in `frappe-bench/` (git-ignored) and symlinks `apps/*` into it.
- `.devcontainer/` — MariaDB + Redis + `frappe/bench` dev stack.
- `docs/architecture.md` — tenancy model and integration design. Read before structural changes.
- `.claude/skills/` — `frappe-*` skills (vendored, don't edit; see FRAPPE_SKILLS_NOTICE.md), plus `frontend-design` and `webapp-testing`.

## Rules

- Never modify Frappe or ERPNext source. Extend through our apps: hooks, `extend_doctype_class`, Custom Fields via fixtures.
- Tenancy is **one Frappe site per customer**. No tenant ID columns; site isolation is the boundary.
- Secrets live in `Password` fields or `site_config.json`, never in code or fixtures.
- Public (`allow_guest=True`) endpoints must verify a signature or token before touching the database.
- Webhook handlers log the event, enqueue the work, and return 200 fast. Heavy work goes in background jobs.
- Keep platform-specific parsing in pure modules (`erp_social/utils/`) with no `frappe` import so they unit-test without a bench.
- Code style: tabs, ruff (config in each app's `pyproject.toml`), line length 110.

## Commands

```bash
# Fast unit tests (no bench needed)
cd apps/erp_social && uv run --no-project --with pytest python -m pytest -q tests
ruff check apps && ruff format --check apps

# Integration tests (inside a bench)
cd frappe-bench && bench --site erp.localhost run-tests --app erp_social
bench --site erp.localhost migrate   # after changing DocType JSON
```

## Workflow

Research → plan → implement. For anything touching more than one app or a DocType schema, plan first
(plan mode) and check the `frappe-agent-architect` skill. Run the `frappe-agent-validator` skill on new
Frappe code before committing. For UI work, use the `frontend-design` skill.
