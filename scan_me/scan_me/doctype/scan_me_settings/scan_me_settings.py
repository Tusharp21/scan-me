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
	}
