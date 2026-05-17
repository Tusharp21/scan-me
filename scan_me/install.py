# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Auto-install Playwright Chromium to {bench}/playwright-browsers/ so PDF
generation works out of the box; failure is non-fatal."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import frappe

# Playwright drops this only after a successful install; a bare chromium-*
# dir without it means a stale or partial download — must re-fetch.
_PLAYWRIGHT_MARKER = "INSTALLATION_COMPLETE"

# Playwright stderr can embed proxy creds / $PATH; bound the Error Log dump.
_INSTALL_LOG_TAIL = 2000


def _browsers_path() -> Path:
	"""Bench-local Chromium cache shared across all apps on this bench."""
	return Path(frappe.utils.get_bench_path()) / "playwright-browsers"


def _truncate_output(label: str, text: str) -> str:
	if not text:
		return f"{label}:\n(empty)"
	text = text.strip()
	if len(text) <= _INSTALL_LOG_TAIL:
		return f"{label}:\n{text}"
	return f"{label} (truncated — showing first {_INSTALL_LOG_TAIL} chars):\n{text[:_INSTALL_LOG_TAIL]}"


def after_install():
	ensure_chromium()


def after_migrate():
	# Re-runs marker validation so a Playwright pip upgrade that invalidated
	# the previous binary triggers a fresh download automatically.
	ensure_chromium()


def ensure_chromium(force=False):
	"""Download Chromium if the cache is missing or invalid; ``force=True``
	wipes and re-downloads. Non-fatal on failure."""
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

	# chromium-headless-shell is the PDF-focused build (~110MB vs ~170MB full).
	env = os.environ.copy()
	env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
	env["NODE_OPTIONS"] = f"{env.get('NODE_OPTIONS', '')} --no-deprecation".strip()

	try:
		# nosemgrep: frappe-subprocess-exec — args are a fixed literal list, no
		# user input; env is os.environ.copy() plus two known keys.
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

	# Auto-install failed — surface the manual command if we're in a request.
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
		# msgprint only fires in a request context; non-request callers fall through.
		pass


def _chromium_cache_valid(base: Path) -> bool:
	"""True only if a chromium* dir contains the INSTALLATION_COMPLETE marker."""
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
