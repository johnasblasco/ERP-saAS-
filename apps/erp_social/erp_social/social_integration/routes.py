"""Tell the SaaS control plane which Meta Page / Instagram IDs this site owns.

The control site receives every Meta webhook for the shared app and forwards each delivery to the
tenant sites that registered the Page or Instagram account it's about. Only runs when site_config
has `saas_control_url` and `saas_tenant_key`; standalone sites receive webhooks directly.
"""

import frappe
import requests

from erp_social.integrations.config import control_plane


def enqueue_route_sync():
	if control_plane():
		frappe.enqueue(
			sync_routes,
			enqueue_after_commit=True,
			deduplicate=True,
			job_id=f"erp_social::routes::{frappe.local.site}",
		)


def owned_meta_ids() -> list[str]:
	ids = set()
	for row in frappe.get_all(
		"Social Platform Account",
		filters={"enabled": 1, "platform": "Facebook"},
		fields=["external_id", "instagram_account_id"],
	):
		ids.update(i for i in (row.external_id, row.instagram_account_id) if i)
	return sorted(ids)


def sync_routes():
	cp = control_plane()
	if not cp:
		return
	response = requests.post(
		f"{cp['url']}/api/method/saas_control.api.routes.sync",
		json={"platform": "Meta", "external_ids": owned_meta_ids()},
		headers={"Authorization": f"Bearer {cp['key']}", "X-Tenant-Site": cp["site"]},
		timeout=20,
	)
	if not response.ok:
		frappe.throw(f"Control plane rejected route sync ({response.status_code}): {response.text[:300]}")
