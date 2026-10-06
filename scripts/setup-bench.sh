#!/usr/bin/env bash
# Create a Frappe v16 bench with ERPNext and this repo's apps, plus two dev sites:
#   control.localhost - the SaaS control plane (saas_control): plans, tenants, billing, routers
#   erp.localhost     - a tenant (erp_social + saas_tenant), registered with the control plane
# Run inside the devcontainer (or any machine with bench, Python 3.14, Node 24, MariaDB, Redis).
# Safe to re-run: existing pieces are kept, missing apps are installed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_DIR="${BENCH_DIR:-$REPO_ROOT/frappe-bench}"
TENANT_SITE="${TENANT_SITE:-erp.localhost}"
CONTROL_SITE="${CONTROL_SITE:-control.localhost}"
DB_HOST="${DB_HOST:-mariadb}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-123}"
REDIS_CACHE="${REDIS_CACHE:-redis://redis-cache:6379}"
REDIS_QUEUE="${REDIS_QUEUE:-redis://redis-queue:6379}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
FRAPPE_BRANCH="${FRAPPE_BRANCH:-version-16}"
WEB_PORT="${WEB_PORT:-8000}"

TENANT_APPS=(erpnext erp_social saas_tenant)
CONTROL_APPS=(erpnext saas_control)

if [ ! -d "$BENCH_DIR" ]; then
  bench init --skip-redis-config-generation --frappe-branch "$FRAPPE_BRANCH" "$BENCH_DIR"
fi
cd "$BENCH_DIR"

bench set-config -g db_host "$DB_HOST"
bench set-config -g redis_cache "$REDIS_CACHE"
bench set-config -g redis_queue "$REDIS_QUEUE"
bench set-config -g redis_socketio "$REDIS_QUEUE"
# Lets the control plane create tenant sites without passing the password on the command line.
bench set-config -g root_password "$DB_ROOT_PASSWORD"
# Route requests to sites by Host header (acme.localhost -> site acme.localhost).
bench config dns_multitenant on

[ -d apps/erpnext ] || bench get-app --branch "$FRAPPE_BRANCH" erpnext

# Link each app in this repo's apps/ into the bench so edits are live.
for app_path in "$REPO_ROOT"/apps/*/; do
  app="$(basename "$app_path")"
  [ -e "apps/$app" ] || ln -s "${app_path%/}" "apps/$app"
  ./env/bin/python -c "import $app" 2>/dev/null || ./env/bin/pip install -e "apps/$app"
  if ! grep -qx "$app" sites/apps.txt; then
    # apps.txt often lacks a trailing newline; appending blindly would glue names together.
    [ -n "$(tail -c1 sites/apps.txt)" ] && echo >> sites/apps.txt
    echo "$app" >> sites/apps.txt
  fi
done
bench build --apps "$(cd "$REPO_ROOT/apps" && ls -d */ | tr -d / | paste -sd, -)"

ensure_site() {
  local site="$1"; shift
  if [ ! -d "sites/$site" ]; then
    bench new-site "$site" \
      --db-root-password "$DB_ROOT_PASSWORD" \
      --admin-password "$ADMIN_PASSWORD" \
      --mariadb-user-host-login-scope='%'
    bench --site "$site" set-config developer_mode 1
    bench --site "$site" set-config allow_tests true
  fi
  local installed
  installed="$(bench --site "$site" list-apps 2>/dev/null | awk '{print $1}')"
  for app in "$@"; do
    grep -qx "$app" <<<"$installed" || bench --site "$site" install-app "$app"
  done
}

ensure_site "$CONTROL_SITE" "${CONTROL_APPS[@]}"
ensure_site "$TENANT_SITE" "${TENANT_APPS[@]}"
# Absolute links (emails, OAuth redirects, webhook URLs) need the dev port.
bench --site "$CONTROL_SITE" set-config host_name "http://$CONTROL_SITE:$WEB_PORT"
bench --site "$TENANT_SITE" set-config host_name "http://$TENANT_SITE:$WEB_PORT"

# The control plane bills tenants through ERPNext, so it needs a Company: run the setup wizard headless.
if [ "$(bench --site "$CONTROL_SITE" execute frappe.is_setup_complete 2>/dev/null | tail -1)" != "true" ]; then
  bench --site "$CONTROL_SITE" execute frappe.desk.page.setup_wizard.setup_wizard.setup_complete --kwargs "{\"args\": {
    \"language\": \"English\", \"country\": \"${COUNTRY:-United States}\", \"timezone\": \"${TIMEZONE:-America/New_York}\",
    \"currency\": \"${CURRENCY:-USD}\", \"company_name\": \"${COMPANY:-SaaS Operator}\", \"company_abbr\": \"SO\",
    \"chart_of_accounts\": \"Standard\", \"fy_start_date\": \"$(date +%Y)-01-01\", \"fy_end_date\": \"$(date +%Y)-12-31\",
    \"setup_demo\": 0, \"enable_telemetry\": 0}}"
fi

# Register the dev tenant with the dev control plane (mirrors what provisioning does).
tenant_key="$(./env/bin/python -c "import json, sys; print(json.load(open(sys.argv[1])).get('saas_tenant_key', ''))" "sites/$TENANT_SITE/site_config.json")"
if [ -z "$tenant_key" ]; then
  bench --site "$CONTROL_SITE" execute saas_control.dev.register_existing_site \
    --kwargs "{\"site_name\": \"$TENANT_SITE\", \"url\": \"http://$TENANT_SITE:$WEB_PORT\"}"
fi
bench use "$TENANT_SITE"

echo "Bench ready at $BENCH_DIR. Start it with: cd $BENCH_DIR && bench start"
echo "  Control plane: http://$CONTROL_SITE:$WEB_PORT  (Administrator / $ADMIN_PASSWORD)"
echo "  Tenant:        http://$TENANT_SITE:$WEB_PORT  (Administrator / $ADMIN_PASSWORD)"
