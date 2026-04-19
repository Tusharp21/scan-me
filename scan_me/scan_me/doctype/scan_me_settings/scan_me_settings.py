# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ScanMeSettings(Document):
	pass


@frappe.whitelist()
def get_allowed_doctypes():
	"""Get list of allowed doctypes for QR generation."""
	settings = frappe.get_single("Scan Me Settings")
	allowed_doctypes = []
	for doc in settings.get("ref_doctype_info"):
		if doc.enable:
			allowed_doctypes.append(doc.ref_doctype)
	return allowed_doctypes


@frappe.whitelist()
def get_form_integration():
	"""Single payload for the form-level JS (allowlist + button visibility flag).

	Called from public/js/hardcopy_button.js on desk load. Combining into one
	call avoids two round trips per form refresh.
	"""
	settings = frappe.get_single("Scan Me Settings")
	allowed = [d.ref_doctype for d in settings.get("ref_doctype_info") if d.enable]
	# Default to on for older installs missing the field.
	show = settings.get("enable_advanced_print_button") in (None, 1, "1", True)
	return {
		"allowed_doctypes": allowed,
		"show_advanced_print_button": 1 if show else 0,
	}


@frappe.whitelist()
def get_print_defaults(doctype):
	"""Return the sensible default Print Format and Letter Head for a doctype.

	Default print format is stored on the DocType record itself
	(``DocType.default_print_format``), not as a flag on Print Format rows.
	Default letter head comes from the Letter Head with ``is_default=1``.
	"""
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(f"DocType {doctype} does not exist.", frappe.DoesNotExistError)
	pf = frappe.db.get_value("DocType", doctype, "default_print_format") or "Standard"
	lh = (
		frappe.db.get_value(
			"Letter Head",
			{"is_default": 1, "disabled": 0},
			"name",
		)
		or ""
	)
	return {"print_format": pf, "letter_head": lh}


@frappe.whitelist()
def get_dialog_settings():
	"""Flags that control which sections render in the Chrome PDF print dialog."""
	s = frappe.get_single("Scan Me Settings")
	# Default to on for any flag missing from older installs.
	return {
		"show_copies": 1 if s.get("show_copies_section") in (None, 1, "1", True) else 0,
		"show_header_footer": 1 if s.get("show_header_footer_section") in (None, 1, "1", True) else 0,
		"show_qr": 1 if s.get("show_qr_section") in (None, 1, "1", True) else 0,
		"show_signature": 1 if s.get("show_signature_section") in (None, 1, "1", True) else 0,
		"show_live_preview": 1 if s.get("show_live_preview") in (None, 1, "1", True) else 0,
		"signature_type": s.get("signature_type") or "Visual Block",
		"watermark_mode": s.get("watermark_mode") or "Disabled",
	}
