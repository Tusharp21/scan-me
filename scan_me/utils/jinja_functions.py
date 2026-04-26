# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
import base64
import re
from io import BytesIO
from urllib.request import urlopen

import frappe
import qrcode
from barcode import get_barcode_class
from barcode.writer import ImageWriter
from frappe.utils import get_url, get_url_to_form
from PIL import Image

from scan_me.utils.verification import build_qr_payload

# ---------------------------------------------------------------------------
# Input bounds
# ---------------------------------------------------------------------------
# All of the functions below are ``@frappe.whitelist(allow_guest=False)`` so any authenticated
# user can call them over HTTP. Unbounded numeric params let a caller request
# a huge PNG (``clearity=100000``) and exhaust server memory; unbounded
# ``size`` strings let them break out of the ``style="..."`` attribute we
# emit on <img> tags. These caps are generous for legitimate template use
# but tight enough to make abuse uninteresting.
MIN_BOX_SIZE = 1
MAX_BOX_SIZE = 20
MIN_BORDER = 0
MAX_BORDER = 10
# QR v40 alphanumeric capacity is 4296 chars; 2953 bytes is the byte-mode
# ceiling. We cap slightly below to keep error-correction headroom.
MAX_QR_DATA_BYTES = 2953
MIN_MODULE_WIDTH = 0.1
MAX_MODULE_WIDTH = 5.0
MIN_MODULE_HEIGHT = 1.0
MAX_MODULE_HEIGHT = 200.0
MIN_QUIET_ZONE = 0.0
MAX_QUIET_ZONE = 20.0
MIN_FONT_SIZE = 0
MAX_FONT_SIZE = 48

# Deliberately narrow: digits (up to 4), optional fractional part, then one
# of a closed set of units. Any character outside this set in the ``size``
# argument could be smuggled through the <img style="..."> attribute to
# enable CSS-based layout abuse or exfiltration via background:url().
CSS_SIZE_RE = re.compile(r"^\d{1,4}(\.\d+)?(mm|cm|px|pt|in|em|rem|%)$")


def _clamp_int(value, *, lo: int, hi: int, name: str) -> int:
	try:
		v = int(value)
	except (TypeError, ValueError):
		frappe.throw(frappe._("{0} must be an integer.").format(name))
	if v < lo or v > hi:
		frappe.throw(frappe._("{0} must be between {1} and {2}.").format(name, lo, hi))
	return v


def _clamp_float(value, *, lo: float, hi: float, name: str) -> float:
	try:
		v = float(value)
	except (TypeError, ValueError):
		frappe.throw(frappe._("{0} must be a number.").format(name))
	if v < lo or v > hi:
		frappe.throw(frappe._("{0} must be between {1} and {2}.").format(name, lo, hi))
	return v


def _sanitize_css_size(size, *, name: str = "size") -> str:
	s = "" if size is None else str(size).strip()
	if not CSS_SIZE_RE.match(s):
		frappe.throw(frappe._("{0} must look like '30mm', '100px', '50%', etc.").format(name))
	return s


def _check_qr_data(data, *, name: str = "data") -> str:
	if data is None or (isinstance(data, str) and not data.strip()):
		frappe.throw(frappe._("{0} cannot be empty.").format(name))
	s = str(data)
	if len(s.encode("utf-8")) > MAX_QR_DATA_BYTES:
		frappe.throw(
			frappe._("{0} is too long to encode in a QR (max {1} bytes).").format(name, MAX_QR_DATA_BYTES)
		)
	return s


# ---------------------------------------------------------------------------
# QR and barcode generators
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=False)
def qr(
	data,
	clearity: int = 8,
	border: int = 4,
	fill_color: str = "black",
	back_color: str = "white",
	include_logo: bool = False,
) -> str:
	"""Render a QR code PNG as a ``data:image/png;base64,...`` URI.

	``clearity`` is ``qrcode``'s ``box_size`` (pixels per module). ``border``
	is the quiet-zone width in modules. Colors accept any Pillow color name
	or hex string. ``include_logo`` overlays the site's ``Website Settings``
	app logo in the QR centre — logo fetch failures are logged and the plain
	QR is returned, so a broken logo never breaks print rendering.
	"""
	payload = _check_qr_data(data)
	box_size = _clamp_int(clearity, lo=MIN_BOX_SIZE, hi=MAX_BOX_SIZE, name="clearity")
	border_px = _clamp_int(border, lo=MIN_BORDER, hi=MAX_BORDER, name="border")

	qr_obj = qrcode.QRCode(version=1, box_size=box_size, border=border_px)
	qr_obj.add_data(payload)
	qr_obj.make(fit=True)
	img = qr_obj.make_image(fill_color=fill_color, back_color=back_color).convert("RGBA")

	if include_logo:
		try:
			ws = frappe.get_doc("Website Settings")
			if ws.app_logo:
				with urlopen(get_url(ws.app_logo)) as r:
					logo = Image.open(BytesIO(r.read())).convert("RGBA")
				qr_w, qr_h = img.size
				logo_size = qr_w // 3
				logo = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
				pos = ((qr_w - logo_size) // 2, (qr_h - logo_size) // 2)
				img.paste(logo, pos, logo)
		except Exception as e:
			frappe.log_error("QR Logo Error", str(e))

	buf = BytesIO()
	img.save(buf, format="PNG")
	return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


@frappe.whitelist(allow_guest=False)
def barcode(
	data,
	barcode_type: str = "code128",
	module_width: float = 0.2,
	module_height: float = 15,
	font_size: int = 10,
	quiet_zone: float = 2,
) -> str:
	"""Render a barcode PNG as a ``data:image/png;base64,...`` URI.

	Returns an empty string for an unknown ``barcode_type`` or a value that
	the chosen type rejects (e.g. letters in an EAN-13), so templates can
	fall back gracefully. Numeric bounds are validated up front — a huge
	``module_height`` would otherwise let a caller request a multi-gigabyte
	PNG.
	"""
	if not data or not str(data).strip():
		return ""

	mw = _clamp_float(module_width, lo=MIN_MODULE_WIDTH, hi=MAX_MODULE_WIDTH, name="module_width")
	mh = _clamp_float(module_height, lo=MIN_MODULE_HEIGHT, hi=MAX_MODULE_HEIGHT, name="module_height")
	qz = _clamp_float(quiet_zone, lo=MIN_QUIET_ZONE, hi=MAX_QUIET_ZONE, name="quiet_zone")
	fs = _clamp_int(font_size, lo=MIN_FONT_SIZE, hi=MAX_FONT_SIZE, name="font_size")

	try:
		BarcodeClass = get_barcode_class(str(barcode_type).lower())
	except Exception:
		return ""  # Invalid barcode type

	try:
		buf = BytesIO()
		writer = ImageWriter()
		writer.set_options(
			{
				"module_width": mw,
				"module_height": mh,
				"quiet_zone": qz,
				"font_size": fs,
			}
		)

		BarcodeClass(str(data), writer=writer).write(buf)
		return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
	except Exception:
		return ""  # Invalid value for the given type


@frappe.whitelist(allow_guest=False)
def qr_link(
	doctype: str,
	name: str,
	clearity: int = 8,
	fill_color: str = "black",
	back_color: str = "white",
	include_logo: bool = False,
) -> str:
	"""QR of the document's desk URL. Throws if ``doctype`` or ``name`` is empty."""
	if not (doctype and name):
		frappe.throw(frappe._("doctype and name are required."))

	doc_url = get_url_to_form(doctype, name)

	return qr(
		doc_url, clearity=clearity, fill_color=fill_color, back_color=back_color, include_logo=include_logo
	)


# ---------------------------------------------------------------------------
# Marker-emitting variants — use these in print formats so the Chrome PDF
# pipeline can detect an existing QR and avoid double-insertion.
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=False)
def qr_img(
	data,
	clearity: int = 8,
	border: int = 4,
	fill_color: str = "black",
	back_color: str = "white",
	include_logo: bool = False,
	size: str = "30mm",
) -> str:
	"""``<img class="scan-me-qr">`` wrapping :func:`qr`.

	``size`` is validated against a strict unit regex because the value is
	interpolated into the emitted ``style="..."`` attribute — without
	validation a caller could smuggle extra CSS declarations (or close the
	attribute and inject markup) through this argument.
	"""
	safe_size = _sanitize_css_size(size)
	src = qr(
		data,
		clearity=clearity,
		border=border,
		fill_color=fill_color,
		back_color=back_color,
		include_logo=include_logo,
	)
	return f'<img class="scan-me-qr" src="{src}" style="width:{safe_size}; height:{safe_size};">'


@frappe.whitelist(allow_guest=False)
def qr_link_img(
	doctype: str,
	name: str,
	clearity: int = 8,
	fill_color: str = "black",
	back_color: str = "white",
	include_logo: bool = False,
	size: str = "30mm",
) -> str:
	"""``<img class="scan-me-qr">`` wrapping :func:`qr_link`. ``size`` is validated."""
	safe_size = _sanitize_css_size(size)
	src = qr_link(
		doctype,
		name,
		clearity=clearity,
		fill_color=fill_color,
		back_color=back_color,
		include_logo=include_logo,
	)
	return f'<img class="scan-me-qr" src="{src}" style="width:{safe_size}; height:{safe_size};">'


# ---------------------------------------------------------------------------
# Verification-aware helpers — encode the Verified QR payload (uuid|hash|sig)
# so third parties can validate integrity via /verify_document.
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=False)
def verify_qr(
	doctype: str,
	name: str,
	clearity: int = 6,
	border: int = 2,
	fill_color: str = "black",
	back_color: str = "white",
) -> str:
	"""Return a QR data-URI encoding the Verified QR payload for this document.

	- If a Verified QR exists, payload is the signed ``uuid|hash|sig`` triple.
	- If no Verified QR exists, returns an empty string (caller should not render).
	"""
	record = frappe.db.get_value(
		"Verified QR",
		{"ref_doctype": doctype, "ref_docname": name},
		["unique_id", "content_hash"],
		as_dict=True,
	)
	if not record or not record.unique_id:
		return ""

	payload = build_qr_payload(record.unique_id, record.content_hash)
	return qr(payload, clearity=clearity, border=border, fill_color=fill_color, back_color=back_color)


@frappe.whitelist(allow_guest=False)
def verify_qr_img(
	doctype: str,
	name: str,
	size: str = "30mm",
	clearity: int = 6,
	border: int = 2,
) -> str:
	"""``<img class="scan-me-qr">`` for :func:`verify_qr`. Empty string if no QR exists."""
	safe_size = _sanitize_css_size(size)
	src = verify_qr(doctype, name, clearity=clearity, border=border)
	if not src:
		return ""
	return f'<img class="scan-me-qr" src="{src}" style="width:{safe_size}; height:{safe_size};">'
