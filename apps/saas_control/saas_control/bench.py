"""Run Frappe CLI commands against sites on this bench (used to create and manage tenant sites).

Uses `python -m frappe.utils.bench_helper frappe ...` from the bench's own virtualenv - the same
entry point the `bench` CLI calls - so workers don't need the bench CLI installed.
The MariaDB root password comes from common_site_config `root_password`, never the command line.
"""

import os
import re
import subprocess

import frappe
from frappe.utils import get_bench_path


class BenchCommandError(Exception):
	pass


class BenchRunner:
	def __init__(self, bench_path: str | None = None, secrets: list[str] | None = None):
		self.bench_path = bench_path or get_bench_path()
		self.secrets = [s for s in (secrets or []) if s]
		self.log: list[str] = []

	def run(self, *args: str, timeout: int = 1800) -> str:
		command = [
			os.path.join(self.bench_path, "env", "bin", "python"),
			"-m",
			"frappe.utils.bench_helper",
			"frappe",
			*args,
		]
		shown = self._mask(" ".join(["bench", *args]))
		self.log.append(f"$ {shown}")
		try:
			result = subprocess.run(
				command,
				cwd=os.path.join(self.bench_path, "sites"),
				capture_output=True,
				text=True,
				timeout=timeout,
				env={**os.environ, "PYTHONUNBUFFERED": "1"},
			)
		except subprocess.TimeoutExpired:
			self.log.append(f"timed out after {timeout}s")
			raise BenchCommandError(f"`{shown}` timed out") from None

		raw = (result.stdout or "") + (result.stderr or "")
		masked = self._mask(raw)
		self.log.append(_tail(masked))
		if result.returncode != 0:
			raise BenchCommandError(f"`{shown}` failed (exit {result.returncode}):\n{_tail(masked, 3000)}")
		return raw  # unmasked for the caller (e.g. to read a setup link); only the log is masked

	def site_exists(self, site: str) -> bool:
		return os.path.isdir(os.path.join(self.bench_path, "sites", site))

	def text_log(self) -> str:
		return "\n".join(self.log)

	def _mask(self, text: str) -> str:
		for secret in self.secrets:
			text = text.replace(secret, "********")
		# Password-setup links printed by saas_tenant.setup.initialize must not sit in logs.
		return re.sub(r"(update-password\?key=)[0-9a-zA-Z]+", r"\1********", text)


def _tail(text: str, limit: int = 1500) -> str:
	text = (text or "").strip()
	return text if len(text) <= limit else "…" + text[-limit:]


def runner(secrets=None) -> BenchRunner:
	path = frappe.db.get_single_value("SaaS Settings", "bench_path") or None
	return BenchRunner(path, secrets=secrets)
