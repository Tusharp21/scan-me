# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Resolve Frappe file URLs to base64 data-URIs for offline-rendered PDFs."""

import base64
import re
from mimetypes import guess_type
from pathlib import Path

import frappe


def get_base64_data_uri(file_url):
	"""Resolve a Frappe file URL to a base64 data-URI.

	File URLs that resolve outside the site's public/files, private/files, or
	the bench ``sites/`` / ``assets/`` directories are rejected — protects
	against path traversal through user-supplied image URLs.
	"""
	if not file_url or file_url.startswith("data:"):
		return file_url or ""

	# NUL bytes in paths are a classic ``open()`` smuggling trick (the C-level
	# truncation can make security checks on one string apply to a different
	# file). Reject early rather than rely on the Python runtime to catch it.
	if "\x00" in file_url:
		return file_url

	# nosemgrep: frappe-security-file-traversal
	site_path = Path(frappe.get_site_path()).resolve()
	bench_path = site_path.parent  # nosemgrep: frappe-security-file-traversal
	disk_path = None

	if file_url.startswith("/private/files/"):
		disk_path = site_path / "private" / "files" / file_url.split("/private/files/", 1)[1]
	elif file_url.startswith("/files/"):
		disk_path = site_path / "public" / "files" / file_url.split("/files/", 1)[1]
	elif file_url.startswith("/assets/"):
		disk_path = bench_path / "sites" / file_url.lstrip("/")
		if not disk_path.exists():
			disk_path = bench_path / file_url.lstrip("/")
	# Fallback matches — catch URLs that embed a ``/private/files/`` or
	# ``/files/`` segment deeper in the path. Kept for compatibility with
	# odd renderings; the containment check below is still the real gate.
	elif "/private/files/" in file_url:
		disk_path = site_path / "private" / "files" / file_url.split("/private/files/", 1)[1]
	elif "/files/" in file_url:
		disk_path = site_path / "public" / "files" / file_url.split("/files/", 1)[1]

	if not disk_path or not disk_path.exists():
		return file_url

	# Contain the resolved path within allowed roots to block ``../`` escapes
	# AND symlinks that point outside the allowlist. Both the candidate and
	# each root are ``resolve()``d so a site whose ``public/files`` is itself
	# a symlink (e.g. mounted storage) still accepts its own files, while
	# resources whose realpath lands outside every allowed root are rejected.
	real = disk_path.resolve()
	allowed_roots = [
		(site_path / "public" / "files").resolve(),
		(site_path / "private" / "files").resolve(),
		(bench_path / "sites" / "assets").resolve(),
		(bench_path / "assets").resolve(),
	]
	if not any(real == root or real.is_relative_to(root) for root in allowed_roots):
		return file_url

	with open(real, "rb") as fh:  # nosemgrep: frappe-security-file-traversal
		b64 = base64.b64encode(fh.read()).decode()
		mime = guess_type(str(real))[0] or "image/png"
		return f"data:{mime};base64,{b64}"


def embed_images(html):
	"""Replace every img-src and CSS url() in *html* with base64 data-URIs."""
	if not html:
		return html or ""

	for m in re.finditer(r'src=["\']([^"\']+)["\']', html):
		url = m.group(1)
		b64 = get_base64_data_uri(url)
		if b64 != url:
			html = html.replace(url, b64)

	for m in re.finditer(r"url\(['\"]?([^)'\">]+)['\"]?\)", html):
		url = m.group(1)
		b64 = get_base64_data_uri(url)
		if b64 != url:
			html = html.replace(url, b64)

	return html
