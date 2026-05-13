# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Install hooks for Scan Me.

Primary job: make sure Playwright's Chromium is downloaded post-install so
PDF generation works out of the box. Failure is non-fatal — the admin sees
a clear message with the manual command.

The Chromium cache lives at ``{bench_path}/playwright-browsers/`` instead
of the user-global ``~/.cache/ms-playwright/`` so it survives Playwright
pip upgrades cleanly and one bench worth of apps shares one cache. The
matching ``PLAYWRIGHT_BROWSERS_PATH`` export happens in ``scan_me/__init__.py``
so every web/worker process picks it up at import time.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import frappe

# Playwright drops this marker file inside a browser dir ONLY after a
# successful install. Treating "dir exists" as cached is what bit us when
# a Playwright pip upgrade left a stale dir behind — launch then failed
# with "Executable doesn't exist". Marker presence is the reliable signal.
_PLAYWRIGHT_MARKER = "INSTALLATION_COMPLETE"

# Caps on the Playwright install output captured into the Error Log on
# failure. Playwright's stderr/stdout can embed proxy URLs (with creds),
# $PATH fragments, and other environment specifics — logging the raw
# output unbounded would be a liability. 2000 chars each is enough to see
# the top traceback and the initial error context for diagnosis.
_INSTALL_LOG_TAIL = 2000


def _browsers_path() -> Path:
	"""Bench-local Chromium cache shared across all apps on this bench."""
	return Path(frappe.utils.get_bench_path()) / "playwright-browsers"


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
	"""Runs after every `bench migrate`. Re-validates the cache so a
	Playwright pip upgrade that invalidated the previous binary triggers a
	fresh download automatically — the original install-only hook missed
	this case and shipped a broken PDF pipeline until manually fixed."""
	ensure_chromium()


def ensure_chromium(force=False):
	"""Download Playwright's Chromium browser if not already present.

	Safe to call repeatedly — verifies the cache via Playwright's
	``INSTALLATION_COMPLETE`` marker (not just dir existence), so stale or
	partial downloads from a previous Playwright version trigger a refresh
	instead of getting silently reused. Pass ``force=True`` to wipe the
	cache and re-download. Non-fatal on failure — logs an Error Log entry
	and shows the admin a message with the manual fallback command.
	"""
	try:
		import playwright  # presence check only — module is referenced via subprocess
	except ImportError:
		frappe.log_error(
			"Scan Me: playwright missing",
			"Playwright is not installed. Run `bench setup requirements` to pick it up.",
		)
		return

	browsers_dir = _browsers_path()

	if force and browsers_dir.exists():
		shutil.rmtree(browsers_dir, ignore_errors=True)

	if not force and _chromium_cache_valid(browsers_dir):
		frappe.log_error(
			"Scan Me: chromium present",
			f"Chromium already cached at {browsers_dir} — skipping download.",
		)
		return

	browsers_dir.mkdir(parents=True, exist_ok=True)

	# Headless-shell is Playwright's PDF-focused build — ~110MB vs full
	# Chromium's ~170MB. Same rendering engine, no UI surface; perfect for
	# server-side PDF generation.
	env = os.environ.copy()
	env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
	env["NODE_OPTIONS"] = f"{env.get('NODE_OPTIONS', '')} --no-deprecation".strip()

	try:
		result = subprocess.run(
			[sys.executable, "-m", "playwright", "install", "chromium-headless-shell"],
			capture_output=True,
			text=True,
			timeout=600,  # 10 min ceiling — download can be slow on shared hosts
			env=env,
		)
		if result.returncode == 0 and _chromium_cache_valid(browsers_dir):
			frappe.log_error(
				"Scan Me: chromium installed",
				f"Chromium downloaded for Scan Me PDF rendering at {browsers_dir}.",
			)
			return

		_cleanup_partial(browsers_dir)
		frappe.log_error(
			"Scan Me: chromium install failed",
			"\n\n".join(
				[
					f"Chromium install exited {result.returncode}. Target: {browsers_dir}",
					_truncate_output("STDERR", result.stderr),
					_truncate_output("STDOUT", result.stdout),
				]
			),
		)
	except subprocess.TimeoutExpired:
		_cleanup_partial(browsers_dir)
		frappe.log_error(
			"Scan Me: chromium install timeout",
			f"Chromium download timed out after 10 minutes. Target: {browsers_dir}",
		)
	except Exception:
		_cleanup_partial(browsers_dir)
		frappe.log_error("Scan Me: chromium install error", frappe.get_traceback())

	# If we got here, the auto-install failed — leave a message for the admin.
	try:
		frappe.msgprint(
			msg=frappe._(
				"Scan Me could not auto-install Chromium for PDF rendering. "
				"Run this command once on the server from your bench directory:<br><br>"
				"<code>PLAYWRIGHT_BROWSERS_PATH={path} ./env/bin/python -m playwright install chromium-headless-shell</code>"
			).format(path=str(browsers_dir)),
			title=frappe._("Scan Me — post-install step needed"),
			indicator="orange",
		)
	except Exception:
		# msgprint only works in a request context; fall through silently otherwise.
		pass


def _chromium_cache_valid(base: Path) -> bool:
	"""True only if a Chromium build dir contains Playwright's success marker.

	A folder named ``chromium*`` alone isn't enough — partial or
	post-upgrade aborted downloads leave the dir behind with no marker,
	and treating that as "cached" is what causes ``BrowserType.launch``
	to fail at runtime with "Executable doesn't exist".
	"""
	if not base.exists():
		return False
	for child in base.iterdir():
		if not child.is_dir():
			continue
		if not child.name.startswith("chromium"):
			continue
		if (child / _PLAYWRIGHT_MARKER).exists():
			return True
	return False


def _cleanup_partial(base: Path) -> None:
	"""Remove half-downloaded Chromium dirs so the next attempt is clean."""
	if not base.exists():
		return
	for child in base.iterdir():
		if child.is_dir() and child.name.startswith("chromium"):
			if not (child / _PLAYWRIGHT_MARKER).exists():
				shutil.rmtree(child, ignore_errors=True)
