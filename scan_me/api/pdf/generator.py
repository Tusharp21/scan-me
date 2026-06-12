# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Whitelisted Chrome-PDF orchestrator; feature work lives in sibling modules."""

import os
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


def _ensure_browsers_path():
	"""Set PLAYWRIGHT_BROWSERS_PATH lazily (keeps __init__ free of side effects).
	Must match install.py's _browsers_path() so the generator finds the cache
	the installer wrote to."""
	bench_browsers = os.path.join(frappe.utils.get_bench_path(), "playwright-browsers")
	os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", bench_browsers)


def _launch_chromium(pw):
	"""Launch headless Chromium, translating a missing-system-library crash into an
	actionable error. Without packages like libatk the binary exits 127 and Playwright
	only reports a generic TargetClosedError — useless for diagnosing a deploy."""
	try:
		return pw.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
	except Exception as e:
		text = str(e)
		if "error while loading shared libraries" in text or "cannot open shared object file" in text:
			frappe.log_error("Chrome PDF: missing system libraries", frappe.get_traceback())
			frappe.throw(
				frappe._("PDF generation is temporarily unavailable. " "Please contact your administrator."),
				frappe.ValidationError,
			)
		raise


@frappe.whitelist(allow_guest=False)
def generate_chrome_pdf(doctype, name, print_format=None, letter_head=None, options=None, preview_mode=0):
	"""Generate a PDF via headless Chromium (Playwright); orchestrates feature modules."""
	if not frappe.has_permission(doctype, "print", name):
		frappe.throw(frappe._("No permission to print this document."), frappe.PermissionError)

	# Gate on Scan Me allowlist so unapproved doctypes can't get QR/watermark/stamps.
	from scan_me.utils.verification import assert_allowed_doctype

	assert_allowed_doctype(doctype)

	# Reject cross-doctype Print Formats: a format targeting doctype B
	# resolving against A's doc could leak unintended fragments.
	# Empty/None and "Standard" are always safe (built-in pseudo-format).
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
	landscape = opts["orientation"] == "Landscape"

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

	# Body-defined id="header-html"/"footer-html" override Letter Head templates;
	# they live in body for HTML preview but become repeating PDF header/footer.
	body_header_html, body_footer_html, body_html = extract_body_header_footer(body_html)
	if body_header_html is not None:
		header_content = body_header_html
		header_h = header_h or 30
	if body_footer_html is not None:
		footer_content = body_footer_html
		footer_h = footer_h or 10

	# Reserve space for copy badge when header is otherwise empty.
	effective_header_h = header_h or (15 if copy_count > 1 else 0)

	if "</head>" in body_html:
		body_html = body_html.replace("</head>", f"<style>{PRINT_CSS}</style>\n</head>", 1)
	else:
		body_html = f"<html><head><style>{PRINT_CSS}</style></head><body>{body_html}</body></html>"

	body_html = _inject_watermark(body_html, opts, doctype, name)
	body_html = _inject_qr_if_needed(body_html, opts, doctype, name)

	# Per-page 'Signature valid' stamp shows most recent signer only.
	sig_records = _fetch_signature_records(doctype, name) if opts.get("append_signature") else None

	_ensure_browsers_path()

	browser = None
	pdf_copies = []
	try:
		with sync_playwright() as pw:
			browser = _launch_chromium(pw)
			page = browser.new_page()

			# Measure rendered header/footer height — Chrome won't auto-size,
			# content exceeding the reserved margin gets clipped.
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
						landscape,
					)
				)

			final_pdf = pdf_copies[0] if len(pdf_copies) == 1 else _merge_pdfs(pdf_copies)

			# Stamp overlay must run while browser is alive (rendered via Playwright).
			if sig_records:
				final_pdf = _apply_signature_stamp_to_pages(final_pdf, sig_records, browser)
	except frappe.ValidationError:
		# Already-actionable message (e.g. missing system libs) — don't mask it.
		raise
	except Exception:
		frappe.log_error("Chrome PDF Generation Failed", frappe.get_traceback())
		frappe.throw(frappe._("PDF generation failed. Check Error Log for details."))
	finally:
		if browser:
			try:
				browser.close()
			except Exception:
				pass

	# Skip crypto signing on live-preview: invisible in iframe, saves 300-500ms.
	is_preview = bool(frappe.utils.cint(preview_mode))
	if not is_preview:
		final_pdf = _maybe_pades_sign(final_pdf, opts, doctype, name)

	safe_name = re.sub(r"[^\w\-.]", "-", name)

	# Only on download — preview runs every keystroke and would litter attachments.
	if not is_preview and opts.get("attach_to_doc"):
		_attach_pdf_to_doc(final_pdf, safe_name, doctype, name)
	frappe.local.response.filename = f"{safe_name}.pdf"
	frappe.local.response.filecontent = final_pdf
	frappe.local.response.type = "pdf"
