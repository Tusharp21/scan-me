# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Fixed-position repeating page watermark. Accepts literal text or __status__ sentinel."""

import re

import frappe

# Sentinel for "Document Status" mode — resolved per-request from the doc.
WATERMARK_STATUS_TOKEN = "__status__"


def _docstatus_label(docstatus: int) -> str:
	"""Function (not module dict) so frappe._ runs per-request against caller locale."""
	if docstatus == 0:
		return frappe._("Draft").upper()
	if docstatus == 2:
		return frappe._("Cancelled").upper()
	return ""


def _resolve_watermark_text(raw, doctype, name):
	"""Resolve final label; __status__ → doc.status, falling back to docstatus label."""
	raw = (raw or "").strip()
	if not raw:
		return ""
	if raw != WATERMARK_STATUS_TOKEN:
		return raw
	try:
		doc = frappe.get_doc(doctype, name)
	except Exception:
		return ""
	status = doc.get("status")
	if status:
		return str(status).upper()
	return _docstatus_label(getattr(doc, "docstatus", 0))


def _inject_watermark(body_html, opts, doctype, name):
	"""Inject a fixed-position watermark that repeats on every PDF page."""
	text = _resolve_watermark_text(opts.get("watermark_text"), doctype, name)
	if not text:
		return body_html

	safe = frappe.utils.escape_html(text)
	# Scale down for long strings so wide statuses still fit on the page.
	font_size = 140 if len(text) <= 10 else max(60, int(1400 / len(text)))
	block = (
		'<div class="sm-watermark" style="'
		"position:fixed; top:50%; left:50%; "
		"transform:translate(-50%,-50%) rotate(-35deg); "
		f"font-size:{font_size}px; font-weight:900; "
		"color:rgba(220,38,38,0.12); letter-spacing:8px; "
		"white-space:nowrap; text-transform:uppercase; "
		"pointer-events:none; z-index:0; "
		"font-family:Arial,Helvetica,sans-serif; "
		'-webkit-print-color-adjust:exact; print-color-adjust:exact;">'
		f"{safe}"
		"</div>"
	)

	m = re.search(r"<body[^>]*>", body_html, re.IGNORECASE)
	if m:
		return body_html[: m.end()] + block + body_html[m.end() :]
	return block + body_html
