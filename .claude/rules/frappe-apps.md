---
paths:
  - "apps/**"
---

# Frappe app conventions

- DocType JSON lives in `<app>/<module>/doctype/<name>/<name>.json`; the controller class name is the
  DocType name in PascalCase. After editing JSON, run `bench --site <site> migrate`.
- Use `frappe.get_all` only where skipping permission checks is intended (e.g. guest webhooks); use `frappe.get_list` for user-facing reads.
- Enqueue background jobs with `enqueue_after_commit=True` and a `job_id` + `deduplicate=True` when retries could double-process.
- Raise user-facing errors with `frappe.throw(_("..."))`; log unexpected failures with `frappe.log_error`.
- Integration tests subclass `frappe.tests.IntegrationTestCase`; mock all outbound HTTP.
- New Custom Fields on ERPNext DocTypes go through `fixtures` in `hooks.py`, filtered by our module.
