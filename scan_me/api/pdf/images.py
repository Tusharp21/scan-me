# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Resolve Frappe file URLs to base64 data-URIs for offline-rendered PDFs."""

import base64
import re
from mimetypes import guess_type
from pathlib import Path

import frappe


def get_base64_data_uri(file_url):
	"""Resolve Frappe file URL to base64 data-URI; paths outside allowed roots rejected."""
	if not file_url or file_url.startswith("data:"):
		return file_url or ""

	# NUL byte smuggles past C-level open() checks — reject early.
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
	# Fallbacks for URLs with /private/files/ or /files/ deeper in the path;
	# the containment check below is still the real gate.
	elif "/private/files/" in file_url:
		disk_path = site_path / "private" / "files" / file_url.split("/private/files/", 1)[1]
	elif "/files/" in file_url:
		disk_path = site_path / "public" / "files" / file_url.split("/files/", 1)[1]

	if not disk_path or not disk_path.exists():
		return file_url

	# resolve() both sides to block ../ escapes AND symlinks pointing outside
	# the allowlist, while still accepting symlinked storage like mounted public/files.
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
