# SaaS Tenant

Installed on every tenant site. The control plane talks to it with the site's `saas_tenant_key`.

- **SaaS Subscription** (single, read-only): plan, status, user limit, trial end.
- Blocks `/api` calls while the workspace is **Suspended** (social webhooks stay open so leads keep
  arriving) and shows trial / payment notices in the desk.
- Enforces the plan's user limit when users are created or enabled.
- `saas_tenant.api.update_subscription` / `usage` for the control plane; `saas_tenant.setup.initialize`
  creates the owner during provisioning.
