# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Inject a fixed-position watermark that repeats on every PDF page.

The client may pass either a literal string (e.g. ``CONFIDENTIAL``) or the
sentinel :data:`WATERMARK_STATUS_TOKEN` to derive the label from the doc's
``status`` field (or its docstatus for unsubmitted/cancelled docs).
"""

import re

import frappe

# Sentinel passed by the client when the user picked the "Document Status" watermark
# mode — the server resolves the actual label from the doc at render time.
WATERMARK_STATUS_TOKEN = "__status__"


def _docstatus_label(docstatus: int) -> str:
	"""Watermark label for a submittable doc with no ``status`` field.

	Intentionally a function (not a module-level dict) so ``frappe._`` runs
	per-request against the caller's locale — caching the translated string
	at import time would pin every render to whatever language happened to
	be active the first time this module was loaded.
	"""
	if docstatus == 0:
		return frappe._("Draft").upper()
	if docstatus == 2:
		return frappe._("Cancelled").upper()
	return ""


def _resolve_watermark_text(raw, doctype, name):
	"""Turn the client-supplied ``watermark_text`` into a final label.

	``__status__`` is a sentinel meaning "use the document's status". We prefer
	an explicit ``status`` field if present (ERPNext sets this on submittable
	docs), otherwise fall back to a Draft/Cancelled label from docstatus.
	"""
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
	# Font size scales down for long strings so very long statuses still fit.
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
