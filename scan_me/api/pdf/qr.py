# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Inject QR into the print body. class="scan-me-qr" marker prevents double-stamping;
qr_force_insert bypasses the check and always injects."""

import re

import frappe

QR_MARKER = 'class="scan-me-qr"'


def _resolve_qr_data(opts, doctype, name):
	"""Pick QR string based on qr_source (Verified QR Link / Custom Text / Document URL)."""
	source = opts.get("qr_source") or "Document URL"
	if source == "Custom Text":
		text = (opts.get("qr_custom_text") or "").strip()
		if text:
			return text
		return frappe.utils.get_url_to_form(doctype, name)
	if source == "Verified QR Link":
		from scan_me.utils.verification import build_qr_payload

		vqr = frappe.db.get_value(
			"Verified QR",
			{"ref_doctype": doctype, "ref_docname": name},
			["unique_id", "content_hash"],
			as_dict=True,
		)
		if vqr and vqr.unique_id:
			return build_qr_payload(vqr.unique_id, vqr.content_hash)
		return frappe.utils.get_url_to_form(doctype, name)
	return frappe.utils.get_url_to_form(doctype, name)


def _build_qr_block(qr_data_uri, position):
	"""Wrap QR in a floated div; float side from Left/Right suffix."""
	float_side = "right" if position.endswith("Right") else "left"
	margin = "margin:0 0 4mm 4mm;" if float_side == "right" else "margin:0 4mm 4mm 0;"
	return (
		f'<div style="float:{float_side}; {margin} padding:2mm; background:white;">'
		f'<img class="scan-me-qr" src="{qr_data_uri}" style="width:25mm; height:25mm; display:block;">'
		"</div>"
		'<div style="clear:both;"></div>'
	)


def _inject_qr_if_needed(body_html, opts, doctype, name):
	"""Inject QR into body; skip if scan-me-qr marker already present (unless force-insert)."""
	if not opts.get("include_qr"):
		return body_html
	if not opts.get("qr_force_insert") and QR_MARKER in body_html:
		return body_html

	from scan_me.utils.jinja_functions import qr as _qr

	try:
		qr_data = _resolve_qr_data(opts, doctype, name)
		qr_src = _qr(qr_data, clearity=6, border=2)
	except Exception:
		frappe.log_error("Chrome PDF: QR generation failed", frappe.get_traceback())
		return body_html

	position = opts.get("qr_position") or "Top Right"
	block = _build_qr_block(qr_src, position)

	if position.startswith("Top"):
		m = re.search(r"<body[^>]*>", body_html, re.IGNORECASE)
		if m:
			return body_html[: m.end()] + block + body_html[m.end() :]
		return block + body_html

	# Bottom
	if re.search(r"</body>", body_html, re.IGNORECASE):
		return re.sub(r"</body>", block + "</body>", body_html, count=1, flags=re.IGNORECASE)
	return body_html + block
