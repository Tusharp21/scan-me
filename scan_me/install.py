# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Install hooks for Scan Me.

Primary job: make sure Playwright's Chromium is downloaded post-install so
PDF generation works out of the box. Failure is non-fatal — the admin sees
a clear message with the manual command.
"""

import subprocess
import sys
from pathlib import Path

import frappe

CHROMIUM_MARKER = "__chromium_installed_marker"


def after_install():
	"""Runs once after `bench install-app scan_me` finishes."""
	ensure_chromium()


def after_migrate():
	"""Runs after every `bench migrate`. Skips download if Chromium is cached."""
	ensure_chromium()


def ensure_chromium(force=False):
	"""Download Playwright's Chromium browser if not already present.

	Safe to call repeatedly — checks the Playwright cache first and skips the
	download when Chromium is already there (e.g. another app on the same
	bench already pulled it, or this is a re-install). Pass ``force=True`` to
	re-download regardless. Non-fatal on failure — logs an Error Log entry
	and shows the admin a message with the manual fallback command.
	"""
	try:
		import playwright
	except ImportError:
		frappe.log_error(
			"Playwright is not installed. Run `bench setup requirements` to pick it up.",
			"Scan Me: playwright missing",
		)
		return

	if not force and _chromium_cache_exists():
		frappe.log_error(
			"Chromium already cached — skipping download.",
			"Scan Me: chromium present",
		)
		return

	try:
		result = subprocess.run(
			[sys.executable, "-m", "playwright", "install", "chromium"],
			capture_output=True,
			text=True,
			timeout=600,  # 10 min ceiling — download can be slow on shared hosts
		)
		if result.returncode == 0:
			frappe.log_error(
				"Chromium downloaded for Scan Me PDF rendering.",
				"Scan Me: chromium installed",
			)
			return

		frappe.log_error(
			f"Chromium install exited {result.returncode}.\nSTDERR:\n{result.stderr}",
			"Scan Me: chromium install failed",
		)
	except subprocess.TimeoutExpired:
		frappe.log_error(
			"Chromium download timed out after 10 minutes.",
			"Scan Me: chromium install timeout",
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Scan Me: chromium install error")

	# If we got here, the auto-install failed — leave a message for the admin.
	try:
		frappe.msgprint(
			msg=frappe._(
				"Scan Me could not auto-install Chromium for PDF rendering. "
				"Run this command once on the server from your bench directory:<br><br>"
				"<code>./env/bin/python -m playwright install chromium</code>"
			),
			title=frappe._("Scan Me — post-install step needed"),
			indicator="orange",
		)
	except Exception:
		# msgprint only works in a request context; fall through silently otherwise.
		pass


def _chromium_cache_exists():
	"""Check the Playwright browser cache for a Chromium folder."""
	# Playwright caches browsers at $PLAYWRIGHT_BROWSERS_PATH, or
	# ~/.cache/ms-playwright on Linux / ~/Library/Caches/ms-playwright on macOS.
	import os

	cache_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
	if cache_env:
		base = Path(cache_env)
	elif sys.platform == "darwin":
		base = Path.home() / "Library" / "Caches" / "ms-playwright"
	else:
		base = Path.home() / ".cache" / "ms-playwright"

	if not base.exists():
		return False
	return any(p.is_dir() and p.name.startswith("chromium") for p in base.iterdir())
