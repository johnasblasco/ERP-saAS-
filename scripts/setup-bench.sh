#!/usr/bin/env bash
# Create a Frappe v16 bench with ERPNext and this repo's apps, plus one dev site.
# Run inside the devcontainer (or any machine with bench, Python 3.14, Node 24, MariaDB, Redis).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_DIR="${BENCH_DIR:-$REPO_ROOT/frappe-bench}"
SITE="${SITE:-erp.localhost}"
DB_HOST="${DB_HOST:-mariadb}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-123}"
REDIS_CACHE="${REDIS_CACHE:-redis://redis-cache:6379}"
REDIS_QUEUE="${REDIS_QUEUE:-redis://redis-queue:6379}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
FRAPPE_BRANCH="${FRAPPE_BRANCH:-version-16}"

if [ ! -d "$BENCH_DIR" ]; then
  bench init --skip-redis-config-generation --frappe-branch "$FRAPPE_BRANCH" "$BENCH_DIR"
fi
cd "$BENCH_DIR"

bench set-config -g db_host "$DB_HOST"
bench set-config -g redis_cache "$REDIS_CACHE"
bench set-config -g redis_queue "$REDIS_QUEUE"
bench set-config -g redis_socketio "$REDIS_QUEUE"

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

if [ ! -d "sites/$SITE" ]; then
  bench new-site "$SITE" \
    --db-root-password "$DB_ROOT_PASSWORD" \
    --admin-password "$ADMIN_PASSWORD" \
    --mariadb-user-host-login-scope='%' \
    --install-app erpnext
  for app_path in "$REPO_ROOT"/apps/*/; do
    bench --site "$SITE" install-app "$(basename "$app_path")"
  done
  bench --site "$SITE" set-config developer_mode 1
  bench --site "$SITE" set-config allow_tests true
  bench use "$SITE"
fi

echo "Bench ready at $BENCH_DIR. Start it with: cd $BENCH_DIR && bench start"
