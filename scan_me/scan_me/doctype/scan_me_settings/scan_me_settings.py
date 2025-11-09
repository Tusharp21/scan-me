# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ScanMeSettings(Document):
	pass

@frappe.whitelist()
def check_button_required(doctype):
	"""Check if 'Generate Verified QR' button should be shown for the given doctype."""
	settings = frappe.get_single("Scan Me Settings")
	allowed_doctypes = [d.ref_doctype for d in settings.get("ref_doctype_info") if d.enable]
	return doctype in allowed_doctypes

@frappe.whitelist()
def get_allowed_doctypes():
	"""Get list of allowed doctypes for QR generation."""
	settings = frappe.get_single("Scan Me Settings")
	allowed_doctypes = []
	for doc in settings.get("ref_doctype_info"):
		if doc.enable:
			allowed_doctypes.append(doc.ref_doctype)
	return allowed_doctypes