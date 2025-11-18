import base64
from io import BytesIO
from urllib.request import urlopen

import frappe
import qrcode
from barcode import get_barcode_class
from barcode.writer import ImageWriter
from frappe.utils import get_url, get_url_to_form
from PIL import Image


@frappe.whitelist()
def qr(data, clearity=8, border=4, fill_color="black", back_color="white", include_logo=False):
	"""Generate a real-time QR code as base64."""
	if not data:
		raise ValueError("QR: data cannot be empty")

	qr_obj = qrcode.QRCode(version=1, box_size=int(clearity), border=int(border))
	qr_obj.add_data(str(data))
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


@frappe.whitelist()
def barcode(data, barcode_type="code128", module_width=0.2, module_height=15, font_size=10, quiet_zone=2):
	"""Generate a real-time barcode as base64.
	If invalid type or value, return blank.
	"""

	if not data or not str(data).strip():
		return ""

	try:
		BarcodeClass = get_barcode_class(barcode_type.lower())
	except Exception:
		return ""  # Invalid barcode type

	try:
		buf = BytesIO()
		writer = ImageWriter()
		writer.set_options(
			{
				"module_width": float(module_width),
				"module_height": float(module_height),
				"quiet_zone": float(quiet_zone),
				"font_size": int(font_size),
			}
		)

		BarcodeClass(str(data), writer=writer).write(buf)
		return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
	except Exception:
		return ""  # Invalid value for the given type


@frappe.whitelist()
def qr_link(doctype, name, clearity=8, fill_color="black", back_color="white", include_logo=False):
	"""Generate QR code for the document using the correct desk URL."""
	if not (doctype and name):
		raise ValueError("doctype and name are required")

	doc_url = get_url_to_form(doctype, name)

	return qr(
		doc_url, clearity=clearity, fill_color=fill_color, back_color=back_color, include_logo=include_logo
	)
