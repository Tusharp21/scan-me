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

# Caps on the Playwright install output captured into the Error Log on
# failure. Playwright's stderr/stdout can embed proxy URLs (with creds),
# $PATH fragments, and other environment specifics — logging the raw
# output unbounded would be a liability. 2000 chars each is enough to see
# the top traceback and the initial error context for diagnosis.
_INSTALL_LOG_TAIL = 2000


def _truncate_output(label: str, text: str) -> str:
	"""Clip subprocess stderr/stdout so a long Playwright dump doesn't flood
	the Error Log (and doesn't include more env info than a reader needs to
	diagnose the failure)."""
	if not text:
		return f"{label}:\n(empty)"
	text = text.strip()
	if len(text) <= _INSTALL_LOG_TAIL:
		return f"{label}:\n{text}"
	return f"{label} (truncated — showing first {_INSTALL_LOG_TAIL} chars):\n{text[:_INSTALL_LOG_TAIL]}"


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
			"Scan Me: playwright missing",
			"Playwright is not installed. Run `bench setup requirements` to pick it up.",
		)
		return

	if not force and _chromium_cache_exists():
		frappe.log_error(
			"Scan Me: chromium present",
			"Chromium already cached — skipping download.",
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
				"Scan Me: chromium installed",
				"Chromium downloaded for Scan Me PDF rendering.",
			)
			return

		frappe.log_error(
			"Scan Me: chromium install failed",
			"\n\n".join(
				[
					f"Chromium install exited {result.returncode}.",
					_truncate_output("STDERR", result.stderr),
					_truncate_output("STDOUT", result.stdout),
				]
			),
		)
	except subprocess.TimeoutExpired:
		frappe.log_error(
			"Scan Me: chromium install timeout",
			"Chromium download timed out after 10 minutes.",
		)
	except Exception:
		frappe.log_error("Scan Me: chromium install error", frappe.get_traceback())

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
