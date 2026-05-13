# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Public ``@frappe.whitelist`` entry point that orchestrates the entire
Chrome-PDF pipeline. All feature work lives in the sibling modules — this file
only wires them together and handles permission/validation gates.
"""

import re

import frappe
from playwright.sync_api import sync_playwright

from .assembly import _merge_pdfs, _render_copy_with_modes
from .attach import _attach_pdf_to_doc
from .css import PRINT_CSS
from .images import embed_images
from .letterhead import (
	_build_footer_template,
	_build_header_template,
	_get_letterhead_raw,
	_measure_html_height_mm,
	extract_body_header_footer,
)
from .options import _parse_copy_labels, _parse_options
from .pades import _maybe_pades_sign
from .qr import _inject_qr_if_needed
from .signature import _apply_signature_stamp_to_pages, _fetch_signature_records
from .watermark import _inject_watermark


@frappe.whitelist(allow_guest=False)
def generate_chrome_pdf(doctype, name, print_format=None, letter_head=None, options=None, preview_mode=0):
	"""Generate a PDF using headless Chromium (Playwright).

	- Header/footer come directly from Letter Head doctype (manage in UI)
	- Page numbers are auto-appended to the footer
	- All images auto-embedded as base64
	- PDF streamed to browser — nothing saved to disk

	``options`` is a JSON string from the print-preview dialog. Implemented:
	multi-copy, QR injection, header/footer repeat modes, 'Signature valid'
	stamp pulled from Verified QR, and optional PAdES digital signature via
	PyHanko (apply_pades; gated by enable_pades_signing in Scan Me Settings).
	"""
	if not frappe.has_permission(doctype, "print", name):
		frappe.throw(frappe._("No permission to print this document."), frappe.PermissionError)

	# Gate on the Scan Me Settings allowlist. Without this, any user with
	# print permission on any doctype could route through this endpoint and
	# get QR injection, watermark, and signature stamps applied — even for
	# doctypes the admin never approved for Scan Me.
	from scan_me.utils.verification import assert_allowed_doctype

	assert_allowed_doctype(doctype)

	# Reject a Print Format that was built for a different doctype. Without
	# this, a caller with print permission on doctype A could invoke a format
	# whose Jinja template targets doctype B — the template would then try to
	# resolve B's fields against A's doc, producing unpredictable output and
	# potentially leaking fragments the admin never intended to render here.
	# Empty / None means "use the doctype's default format", and the literal
	# ``Standard`` is Frappe's built-in pseudo-format (not a DB row) that
	# renders every doctype with the stock template — both are always safe,
	# so we only validate when a real, named Print Format is supplied.
	print_format = (print_format or "").strip() or None
	if print_format and print_format != "Standard":
		pf_doctype = frappe.db.get_value("Print Format", print_format, "doc_type")
		if pf_doctype is None:
			frappe.throw(
				frappe._("Print Format '{0}' does not exist.").format(print_format),
				frappe.DoesNotExistError,
			)
		if pf_doctype != doctype:
			frappe.throw(
				frappe._("Print Format '{0}' is for '{1}', not '{2}'.").format(
					print_format, pf_doctype, doctype
				),
				frappe.ValidationError,
			)

	opts = _parse_options(options)
	copy_count = opts["copy_count"]
	copy_labels = _parse_copy_labels(opts["copy_labels"], copy_count)
	header_mode = opts["header_mode"]
	footer_mode = opts["footer_mode"]

	if letter_head == "No Letterhead":
		letter_head = None

	if not frappe.db.exists(doctype, name):
		frappe.throw(
			frappe._("{0} {1} does not exist.").format(doctype, name),
			frappe.DoesNotExistError,
		)

	header_content, footer_content, header_h, footer_h = _get_letterhead_raw(letter_head)

	body_html = frappe.get_print(
		doctype,
		name,
		print_format=print_format,
		as_pdf=False,
		no_letterhead=True,
	)
	body_html = re.sub(r'<div class="action-banner.*?">.*?</div>', "", body_html, flags=re.DOTALL)
	body_html = embed_images(body_html)

	# Body-defined header/footer (id="header-html" / id="footer-html") override
	# the letter-head templates. They're commonly kept in the body so HTML print
	# preview can show them; for the actual PDF they belong in the repeating
	# page header/footer.
	body_header_html, body_footer_html, body_html = extract_body_header_footer(body_html)
	if body_header_html is not None:
		header_content = body_header_html
		header_h = header_h or 30
	if body_footer_html is not None:
		footer_content = body_footer_html
		footer_h = footer_h or 10

	# If there's no header but we still need a copy badge, reserve space.
	effective_header_h = header_h or (15 if copy_count > 1 else 0)

	if "</head>" in body_html:
		body_html = body_html.replace("</head>", f"<style>{PRINT_CSS}</style>\n</head>", 1)
	else:
		body_html = f"<html><head><style>{PRINT_CSS}</style></head><body>{body_html}</body></html>"

	body_html = _inject_watermark(body_html, opts, doctype, name)
	body_html = _inject_qr_if_needed(body_html, opts, doctype, name)

	# Signature records drive the per-page 'Signature valid' stamp applied
	# after rendering. The stamp always shows the most recent signer — it's a
	# fixed-size overlay marker, not a multi-signer list.
	sig_records = _fetch_signature_records(doctype, name) if opts.get("append_signature") else None

	browser = None
	pdf_copies = []
	try:
		with sync_playwright() as pw:
			browser = pw.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
			page = browser.new_page()

			# Measure actual rendered height of header/footer templates so the
			# page margin matches their real size. Chrome won't auto-size its
			# header/footer area — content taller than the reserved margin
			# gets clipped.
			measure_page = browser.new_page()
			try:
				sample_header = _build_header_template(header_content, copy_labels[0])
				sample_footer = _build_footer_template(footer_content)
				measured_h = _measure_html_height_mm(measure_page, sample_header)
				measured_f = _measure_html_height_mm(measure_page, sample_footer)
			finally:
				measure_page.close()
			if measured_h > 0:
				effective_header_h = measured_h
			if measured_f > 0:
				footer_h = measured_f

			margins = {
				"top": f"{effective_header_h + 5}mm",
				"bottom": f"{footer_h + 8.5}mm",
				"left": "10mm",
				"right": "10mm",
			}

			page.set_content(body_html, wait_until="load", timeout=30000)
			page.emulate_media(media="print")
			page.wait_for_timeout(500)

			for label in copy_labels:
				pdf_copies.append(
					_render_copy_with_modes(
						page,
						label,
						header_content,
						footer_content,
						margins,
						header_mode,
						footer_mode,
					)
				)

			final_pdf = pdf_copies[0] if len(pdf_copies) == 1 else _merge_pdfs(pdf_copies)

			# Per-page 'Signature valid' stamp. Must run while the browser is
			# still alive since the overlay is rendered via Playwright.
			if sig_records:
				final_pdf = _apply_signature_stamp_to_pages(final_pdf, sig_records, browser)
	except Exception:
		frappe.log_error("Chrome PDF Generation Failed", frappe.get_traceback())
		frappe.throw(frappe._("PDF generation failed. Check Error Log for details."))
	finally:
		if browser:
			try:
				browser.close()
			except Exception:
				pass

	# Skip expensive crypto signing on live-preview requests — Adobe's signature
	# panel isn't visible in the preview iframe anyway, and skipping saves ~300-500ms.
	is_preview = bool(frappe.utils.cint(preview_mode))
	if not is_preview:
		final_pdf = _maybe_pades_sign(final_pdf, opts, doctype, name)

	safe_name = re.sub(r"[^\w\-.]", "-", name)

	# Attach the fully-rendered PDF to the source document when requested.
	# Only on download (preview_mode off) — preview runs on every keystroke
	# and attaching each time would litter the document with files.
	if not is_preview and opts.get("attach_to_doc"):
		_attach_pdf_to_doc(final_pdf, safe_name, doctype, name)
	frappe.local.response.filename = f"{safe_name}.pdf"
	frappe.local.response.filecontent = final_pdf
	frappe.local.response.type = "pdf"
