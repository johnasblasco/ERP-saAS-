#!/usr/bin/env bash
# Integration tests inside the official ERPNext image (used by CI; works locally too):
#
#   docker run --rm --network host -v "$PWD":/workspace \
#     -e DB_HOST=127.0.0.1 -e REDIS_CACHE=redis://127.0.0.1:6379 -e REDIS_QUEUE=redis://127.0.0.1:6379 \
#     frappe/erpnext:v16.50.0 bash /workspace/scripts/ci-test.sh
#
# Needs MariaDB (root password $DB_ROOT_PASSWORD, default 123) and Redis reachable from the container.
set -euo pipefail

export BENCH_DIR=/home/frappe/frappe-bench
bash "$(dirname "${BASH_SOURCE[0]}")/setup-bench.sh"

cd "$BENCH_DIR"
bench --site erp.localhost run-tests --app erp_social
bench --site erp.localhost run-tests --app saas_tenant
bench --site control.localhost run-tests --app saas_control
