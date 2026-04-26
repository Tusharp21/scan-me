# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
import base64
import json
import re
from io import BytesIO
from mimetypes import guess_type
from pathlib import Path

import frappe
from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter

MAX_COPIES = 5


# ---------------------------------------------------------------------------
# Options schema passed by the Advanced Print page (scan_me/scan_me/page/scan_me_print/scan_me_print.js)
# ---------------------------------------------------------------------------
# copy_count         int    1/2/3
# copy_labels        str    comma-separated, e.g. "ORIGINAL, DUPLICATE"
# header_mode        str    "All pages" | "First page only" | "Last page only"
#                           | "First and last pages" | "None"
# footer_mode        str    same options as header_mode
# include_qr         0/1
# qr_position        str    "Top Right" | "Top Left" | "Bottom Right" | "Bottom Left"
# qr_source          str    "Verified QR Link" | "Document URL" | "Custom Text"
# qr_custom_text     str
# qr_force_insert    0/1    skip marker detection and always inject
# append_signature   0/1
# watermark_text     str    literal text, or "__status__" to derive from doc
# ---------------------------------------------------------------------------

DEFAULT_OPTIONS = {
	"copy_count": 1,
	"copy_labels": "",
	"header_mode": "All pages",
	"footer_mode": "All pages",
	"include_qr": 0,
	"qr_position": "Top Right",
	"qr_source": "Verified QR Link",
	"qr_custom_text": "",
	"qr_force_insert": 0,
	"append_signature": 0,
	"apply_pades": 0,
	"watermark_text": "",
	"attach_to_doc": 0,
}

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


def _parse_options(raw):
	if not raw:
		return dict(DEFAULT_OPTIONS)
	if isinstance(raw, dict):
		parsed = raw
	else:
		try:
			parsed = json.loads(raw)
		except (ValueError, TypeError):
			parsed = {}
	merged = dict(DEFAULT_OPTIONS)
	merged.update({k: v for k, v in parsed.items() if k in DEFAULT_OPTIONS})
	try:
		merged["copy_count"] = max(1, min(int(merged["copy_count"]), MAX_COPIES))
	except (ValueError, TypeError):
		merged["copy_count"] = 1
	return merged


def _parse_copy_labels(raw, count):
	"""Split comma-separated labels and pad with auto-generated names if short.

	If ``raw`` is empty/whitespace, no stamps are applied — N plain copies are
	rendered without any badge. Labels are therefore optional on multi-copy PDFs.
	"""
	if count <= 1:
		return [""]
	raw = (raw or "").strip()
	if not raw:
		return [""] * count
	labels = [s.strip() for s in raw.split(",") if s.strip()]
	while len(labels) < count:
		labels.append(f"COPY {len(labels) + 1}")
	return labels[:count]


# ---------------------------------------------------------------------------
# QR injection
# ---------------------------------------------------------------------------

QR_MARKER = 'class="scan-me-qr"'


def _resolve_qr_data(opts, doctype, name):
	"""Work out what string goes into the QR based on qr_source."""
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
	"""Wrap a QR data-URI in a floated div for injection into the body flow.

	Top positions inject at the start of <body>, bottom positions at the end.
	Float direction follows the Left/Right suffix.
	"""
	float_side = "right" if position.endswith("Right") else "left"
	margin = "margin:0 0 4mm 4mm;" if float_side == "right" else "margin:0 4mm 4mm 0;"
	return (
		f'<div style="float:{float_side}; {margin} padding:2mm; background:white;">'
		f'<img class="scan-me-qr" src="{qr_data_uri}" style="width:25mm; height:25mm; display:block;">'
		"</div>"
		'<div style="clear:both;"></div>'
	)


def _inject_qr_if_needed(body_html, opts, doctype, name):
	"""Inject a QR image into the body per options; skip if one is already present."""
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


# ---------------------------------------------------------------------------
# Watermark
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Signature stamp
# ---------------------------------------------------------------------------


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


def _attach_pdf_to_doc(pdf_bytes, safe_name, doctype, name):
	"""Save the rendered PDF as a File record attached to the source document.

	Uses Frappe's ``save_file`` helper which correctly handles content
	persistence (writes to disk, hashes, etc.). Permission check is explicit so
	we can log the refusal. Failures are logged, not raised — the user still
	gets their download.
	"""
	if not frappe.has_permission(doctype, "write", name):
		frappe.log_error(
			"Scan Me: attach PDF denied",
			f"User {frappe.session.user} tried to attach PDF without write access to {doctype} {name}",
		)
		return

	try:
		from frappe.utils.file_manager import save_file

		save_file(
			fname=f"{safe_name}.pdf",
			content=pdf_bytes,
			dt=doctype,
			dn=name,
			is_private=1,
		)
		frappe.db.commit()  # ensure the File row persists even with response streaming
	except Exception:
		frappe.log_error("Scan Me: attach PDF failed", frappe.get_traceback())


def _maybe_pades_sign(pdf_bytes, opts, doctype, name):
	"""Run the merged PDF through PyHanko if the user asked for PAdES signing.

	Requires:
	  - enable_pades_signing = 1 in Scan Me Settings (admin-gated)
	  - apply_pades = 1 in the dialog (user-selected per-render)
	Silently returns the unsigned bytes if either is off. Logs and returns
	unsigned bytes on signing failure to avoid losing the document.
	"""
	if not opts.get("apply_pades"):
		return pdf_bytes

	from scan_me.utils.verification import get_signing_settings

	if not get_signing_settings()["enable_pades_signing"]:
		return pdf_bytes

	try:
		from scan_me.utils.pades import sign_pdf

		signers = _fetch_signature_records(doctype, name) or None
		return sign_pdf(pdf_bytes, doctype, name, signers=signers)
	except Exception:
		frappe.log_error("Scan Me: PAdES signing failed", frappe.get_traceback())
		return pdf_bytes


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Core PDF generator
# ---------------------------------------------------------------------------


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

	# If there's no letterhead header but we still need a copy badge, reserve space.
	effective_header_h = header_h or (15 if copy_count > 1 else 0)

	body_html = frappe.get_print(
		doctype,
		name,
		print_format=print_format,
		as_pdf=False,
		no_letterhead=True,
	)
	body_html = re.sub(r'<div class="action-banner.*?">.*?</div>', "", body_html, flags=re.DOTALL)
	body_html = embed_images(body_html)

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

	margins = {
		"top": f"{effective_header_h + 5}mm",
		"bottom": f"{footer_h + 8.5}mm",
		"left": "10mm",
		"right": "10mm",
	}

	browser = None
	pdf_copies = []
	try:
		with sync_playwright() as pw:
			browser = pw.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
			page = browser.new_page()
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_letterhead_raw(letter_head_name):
	"""Read Letter Head from DB and return the raw (image-embedded) content HTML.

	For page numbers, add these in the Letter Head footer HTML:
	  <span class="pageNumber"></span>  — current page
	  <span class="totalPages"></span>  — total pages

	Returns: (header_content_html, footer_content_html, header_h_mm, footer_h_mm)
	"""
	if not letter_head_name:
		return "", "", 0, 0

	if not frappe.db.exists("Letter Head", letter_head_name):
		# Letter Head was deleted or renamed — fall back to no-letterhead render.
		return "", "", 0, 0
	lh = frappe.get_doc("Letter Head", letter_head_name)
	header_content = embed_images(lh.get("content") or "")
	footer_content = embed_images(lh.get("footer") or "")
	header_h = 30 if header_content else 0
	footer_h = 10 if footer_content else 0
	return header_content, footer_content, header_h, footer_h


def _build_header_template(header_content, copy_label=""):
	"""Build Playwright header template HTML, optionally with a copy-label badge."""
	badge = ""
	if copy_label:
		safe_label = frappe.utils.escape_html(copy_label)
		badge = (
			'<div style="padding:2px 10px; border:2px solid #d63030; color:#d63030; '
			"font-weight:bold; font-size:11px; letter-spacing:1.5px; background:white; "
			f'white-space:nowrap;">{safe_label}</div>'
		)

	if not header_content and not badge:
		return "<div></div>"

	return (
		'<div style="width:100%; font-size:12px; padding:2mm 10mm; box-sizing:border-box; '
		'display:flex; justify-content:space-between; align-items:flex-start;">'
		f'<div style="flex:1;">{header_content}</div>'
		f'<div style="flex:0 0 auto; margin-left:10mm;">{badge}</div>'
		"</div>"
	)


def _build_footer_template(footer_content):
	"""Build Playwright footer template HTML."""
	if not footer_content:
		return "<div></div>"
	return (
		'<div style="width:100%; font-size:10px; padding:2mm 10mm; box-sizing:border-box;">'
		f"{footer_content}"
		"</div>"
	)


def _merge_pdfs(pdf_bytes_list):
	"""Concatenate a list of PDF byte blobs into a single PDF."""
	writer = PdfWriter()
	for pdf_bytes in pdf_bytes_list:
		reader = PdfReader(BytesIO(pdf_bytes))
		for page in reader.pages:
			writer.add_page(page)
	out = BytesIO()
	writer.write(out)
	return out.getvalue()


# ---------------------------------------------------------------------------
# Header / footer repeat modes
# ---------------------------------------------------------------------------


def _pages_with_status(total, mode):
	"""Return 1-indexed page numbers where header/footer should appear."""
	if total <= 0:
		return set()
	if mode == "All pages":
		return set(range(1, total + 1))
	if mode == "First page only":
		return {1}
	if mode == "Last page only":
		return {total}
	if mode == "First and last pages":
		return {1, total}
	return set()  # "None"


def _group_pages_by_status(total, header_on, footer_on):
	"""Yield (start, end, has_header, has_footer) for each run of consecutive same-status pages."""
	current_status = None
	run_start = None
	run_end = None
	for p in range(1, total + 1):
		status = (p in header_on, p in footer_on)
		if current_status is None:
			current_status = status
			run_start = p
			run_end = p
		elif status == current_status:
			run_end = p
		else:
			yield run_start, run_end, current_status[0], current_status[1]
			current_status = status
			run_start = p
			run_end = p
	if current_status is not None:
		yield run_start, run_end, current_status[0], current_status[1]


def _render_copy_with_modes(page, label, header_content, footer_content, margins, header_mode, footer_mode):
	"""Render one complete copy respecting header_mode / footer_mode.

	Fast paths avoid extra renders when both modes are All/All or None/None.
	Otherwise: render once to learn page count, then render each group of
	consecutive same-status pages with appropriate templates and merge.
	Margins stay constant across renders so page breaks don't shift.
	"""
	full_header = _build_header_template(header_content, label)
	full_footer = _build_footer_template(footer_content)
	empty_tpl = "<div></div>"

	if header_mode == "All pages" and footer_mode == "All pages":
		return page.pdf(
			format="A4",
			display_header_footer=True,
			header_template=full_header,
			footer_template=full_footer,
			print_background=True,
			margin=margins,
		)

	if header_mode == "None" and footer_mode == "None":
		return page.pdf(
			format="A4",
			display_header_footer=True,
			header_template=empty_tpl,
			footer_template=empty_tpl,
			print_background=True,
			margin=margins,
		)

	# Need page count — do one reference render with full H/F.
	reference = page.pdf(
		format="A4",
		display_header_footer=True,
		header_template=full_header,
		footer_template=full_footer,
		print_background=True,
		margin=margins,
	)
	total = len(PdfReader(BytesIO(reference)).pages)
	header_on = _pages_with_status(total, header_mode)
	footer_on = _pages_with_status(total, footer_mode)

	groups = list(_group_pages_by_status(total, header_on, footer_on))

	# If the reference already matches the desired layout, return it as-is.
	if len(groups) == 1 and groups[0][2] and groups[0][3]:
		return reference

	writer = PdfWriter()
	for start, end, has_header, has_footer in groups:
		hdr = full_header if has_header else empty_tpl
		ftr = full_footer if has_footer else empty_tpl
		segment = page.pdf(
			format="A4",
			display_header_footer=True,
			header_template=hdr,
			footer_template=ftr,
			print_background=True,
			margin=margins,
			page_ranges=f"{start}-{end}",
		)
		for p in PdfReader(BytesIO(segment)).pages:
			writer.add_page(p)
	out = BytesIO()
	writer.write(out)
	return out.getvalue()


# ---------------------------------------------------------------------------
# Print CSS — injected into every PDF for proper table pagination
# ---------------------------------------------------------------------------

PRINT_CSS = """
	body { margin:0; background:white !important; }
	* {
		-webkit-print-color-adjust:exact !important;
		print-color-adjust:exact !important;
		}
	thead { display:table-header-group; }
	tfoot { display:table-footer-group; }
	tbody { display:table-row-group; }
	tr {
		page-break-inside:auto;
		break-inside:auto;
		}
	td, th {
		page-break-inside:auto;
		break-inside:auto;
		overflow-wrap:break-word;
		word-wrap:break-word;
		-webkit-box-decoration-break:clone;
		box-decoration-break:clone;
	}
	td div, td p, td span {
		page-break-inside:auto;
		break-inside:auto;
		overflow-wrap:break-word;
		word-wrap:break-word;
	}
	h1,h2,h3,h4,h5,h6 {
		page-break-after:avoid;
		break-after:avoid;
	}
"""
