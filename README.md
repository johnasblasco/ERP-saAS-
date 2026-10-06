# ERP SaaS

Multi-tenant ERP on Frappe + ERPNext v16, connected to Facebook, Instagram and TikTok.

## Quick start

1. Open the repo in VS Code and choose **Reopen in Container** (or `docker compose -f .devcontainer/docker-compose.yml up -d`, then run a shell in the `frappe` service).
2. The container runs `scripts/setup-bench.sh`, which builds `frappe-bench/` with ERPNext and every app in `apps/`, and creates the site `erp.localhost` (login `Administrator` / `admin`).
3. `cd frappe-bench && bench start`, then open http://erp.localhost:8000.

## Apps

- [`apps/erp_social`](apps/erp_social) — Facebook / Instagram / TikTok lead capture into ERPNext CRM.

See [docs/architecture.md](docs/architecture.md) for the tenancy model and integration design.
