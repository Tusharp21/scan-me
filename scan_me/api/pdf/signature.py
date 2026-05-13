# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Build per-page 'Signature valid' / 'Signature invalid' stamps from
Verified QR records and overlay them onto every page of the merged PDF.

The stamp shows the most recent signer only — it's a fixed-size visual marker,
not a multi-signer list. Tamper status is computed by re-hashing the document
and comparing against the stored hash.
"""

from io import BytesIO

import frappe
from pypdf import PdfReader, PdfWriter


def _fetch_signature_records(doctype, name):
	"""Return a list of signature-info dicts, one per Verified QR for this doc.

	Signature records are ordered by signed_on / creation. Each dict includes
	``tamper_status`` computed against the current doc content hash.
	"""
	rows = frappe.db.get_all(
		"Verified QR",
		filters={"ref_doctype": doctype, "ref_docname": name},
		fields=["unique_id", "signed_by", "signature", "signed_on", "creation", "content_hash"],
		order_by="signed_on asc, creation asc",
	)
	if not rows:
		return []

	current_hash = None
	try:
		from scan_me.utils.verification import compute_doc_hash, verify_stored_hash

		current_hash = compute_doc_hash(doctype, name)
	except Exception:
		current_hash = None
		verify_stored_hash = None  # type: ignore[assignment]

	results = []
	for r in rows:
		info = {
			"unique_id": r.unique_id or "",
			"signature": r.signature or "",
			"full_name": "",
			"email": "",
			"signed_on": "",
			"content_hash": r.content_hash or "",
			"tamper_status": "unknown",
		}

		if r.signed_by:
			user = frappe.db.get_value("User", r.signed_by, ["full_name", "email"], as_dict=True)
			if user:
				info["full_name"] = user.full_name or r.signed_by
				info["email"] = user.email or r.signed_by
			else:
				info["full_name"] = r.signed_by
				info["email"] = r.signed_by

		ts = r.signed_on or r.creation
		if ts:
			try:
				info["signed_on"] = frappe.utils.format_datetime(ts, "dd-MMM-yyyy HH:mm:ss")
			except Exception:
				info["signed_on"] = str(ts)

		if r.content_hash and current_hash and verify_stored_hash:
			# verify_stored_hash transparently handles both the v1:HMAC
			# format (for records signed after the hash-wrapping rollout)
			# and legacy plain-sha256 records (pre-v1).
			matches = verify_stored_hash(
				r.content_hash, doctype, name, r.signed_by, current_plain=current_hash
			)
			info["tamper_status"] = "verified" if matches else "tampered"
			info["current_hash"] = current_hash
		elif r.content_hash:
			info["tamper_status"] = "unknown"  # couldn't compute current hash
		else:
			info["tamper_status"] = "unhashed"  # no hash recorded (older/toggled off)

		results.append(info)

	return results


def _build_page_stamp_overlay_html(record):
	"""A4 transparent page with a PlotSoft-style 'Signature valid' stamp at bottom-right.

	Rendered once with Playwright and then merged onto every page of the main
	PDF via :func:`_apply_signature_stamp_to_pages`. Green border + checkmark
	when the content hash matches; red border + cross when the document has
	been modified since signing.
	"""
	esc = frappe.utils.escape_html
	status = record.get("tamper_status") or "unhashed"
	tampered = status == "tampered"

	name = esc(record.get("full_name") or "Unknown")
	date = esc(record.get("signed_on") or "")
	uid = esc((record.get("unique_id") or "")[:18])

	if tampered:
		title = "Signature invalid"
		border_color = "#dc2626"
		title_color = "#991b1b"
		mark_color = "#dc2626"
		mark_svg = (
			'<path d="M6 6 L26 26 M26 6 L6 26" stroke="currentColor" '
			'stroke-width="5" stroke-linecap="round" fill="none"/>'
		)
	else:
		title = "Signature valid"
		border_color = "#059669"
		title_color = "#111827"
		mark_color = "#059669"
		mark_svg = (
			'<path d="M5 17 L13 25 L28 8" stroke="currentColor" '
			'stroke-width="5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
		)

	return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  @page {{ size: A4; margin: 0; }}
  html, body {{ margin:0; padding:0; width:210mm; height:297mm; background:transparent; }}
  body {{ position: relative; }}
  .sm-stamp-box {{
    position: absolute;
    right: 10mm;
    bottom: 18mm;
    width: 80mm;
    min-height: 24mm;
    border: 1.4px solid {border_color};
    background: #ffffff;
    padding: 3mm 26mm 3mm 4mm;
    font-family: Arial, Helvetica, sans-serif;
    box-sizing: border-box;
    overflow: hidden;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  .sm-stamp-title {{
    font-size: 13px;
    font-weight: 900;
    color: {title_color};
    margin-bottom: 1.2mm;
    letter-spacing: 0.2px;
  }}
  .sm-stamp-line {{
    font-size: 9px;
    color: #374151;
    line-height: 1.4;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .sm-stamp-mark {{
    position: absolute;
    right: 2mm;
    top: 50%;
    transform: translateY(-50%);
    width: 20mm;
    height: 20mm;
    color: {mark_color};
    opacity: 0.85;
  }}
</style></head>
<body>
  <div class="sm-stamp-box">
    <div class="sm-stamp-title">{title}</div>
    <div class="sm-stamp-line">Digitally signed by <b>{name}</b></div>
    <div class="sm-stamp-line">Date: {date}</div>
    <div class="sm-stamp-line">Reason: Document authenticity</div>
    <div class="sm-stamp-line">ID: {uid}</div>
    <svg class="sm-stamp-mark" viewBox="0 0 32 32">{mark_svg}</svg>
  </div>
</body></html>"""


def _apply_signature_stamp_to_pages(pdf_bytes, records, browser):
	"""Overlay the 'Signature valid' stamp on every page of the input PDF.

	Uses the most recent signer only — the stamp is a fixed-size visual marker,
	so multi-signer rendering isn't supported here. On any failure we log and
	return the original bytes so the user still gets a usable PDF.
	"""
	if not records:
		return pdf_bytes

	try:
		stamp_page = browser.new_page()
		try:
			stamp_page.set_content(
				_build_page_stamp_overlay_html(records[-1]), wait_until="load", timeout=10000
			)
			stamp_page.emulate_media(media="print")
			stamp_pdf_bytes = stamp_page.pdf(
				format="A4",
				print_background=True,
				margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
			)
		finally:
			stamp_page.close()
	except Exception:
		frappe.log_error("Scan Me: signature stamp render failed", frappe.get_traceback())
		return pdf_bytes

	try:
		reader = PdfReader(BytesIO(pdf_bytes))
		stamp_reader = PdfReader(BytesIO(stamp_pdf_bytes))
		overlay = stamp_reader.pages[0]
		writer = PdfWriter()
		for page_obj in reader.pages:
			page_obj.merge_page(overlay)
			writer.add_page(page_obj)
		out = BytesIO()
		writer.write(out)
		return out.getvalue()
	except Exception:
		frappe.log_error("Scan Me: signature stamp overlay failed", frappe.get_traceback())
		return pdf_bytes
