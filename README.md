# ERP SaaS

Hosted ERP on Frappe + ERPNext v16. Each customer gets their own workspace at `<name>.<your-domain>`.
Leads from Facebook, Instagram and TikTok ads, plus Messenger and Instagram chats, flow into their CRM.

## Apps

- [`apps/saas_control`](apps/saas_control) is the operator's control site. It handles the signup page, plans, provisioning, billing through ERPNext Subscriptions, and webhook and OAuth routing.
- [`apps/saas_tenant`](apps/saas_tenant) is installed on every workspace. It holds the plan state, enforces user limits and suspension, and reports usage.
- [`apps/erp_social`](apps/erp_social) connects social accounts, captures leads, handles DMs and replies, and syncs ad audiences.

How they fit together: [docs/architecture.md](docs/architecture.md). Running it in production: [docs/deployment.md](docs/deployment.md).

## Develop

1. Open the repo in VS Code and choose **Reopen in Container**. Alternatively, run `docker compose -f .devcontainer/docker-compose.yml up -d` and open a shell in the `frappe` service.
2. `bash scripts/setup-bench.sh` builds `frappe-bench/` with two sites:
   - `control.localhost` runs the control plane. The signup page is at `/signup`.
   - `erp.localhost` is a tenant, already registered with the control plane.
   - Both use `Administrator` / `admin`.
3. `cd frappe-bench && bench start`, then open http://control.localhost:8000 or http://erp.localhost:8000.

## Test

```bash
# Unit tests: fast, no bench needed
(cd apps/erp_social && uv run --no-project --with pytest --with requests python -m pytest -q tests)
(cd apps/saas_control && uv run --no-project --with pytest python -m pytest -q tests)

# Integration tests: real ERPNext v16 in Docker (same as CI)
docker run --rm --network host -v "$PWD":/workspace \
  -e DB_HOST=127.0.0.1 -e REDIS_CACHE=redis://127.0.0.1:6379 -e REDIS_QUEUE=redis://127.0.0.1:6379 \
  frappe/erpnext:v16.50.0 bash /workspace/scripts/ci-test.sh
```
