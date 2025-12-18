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
