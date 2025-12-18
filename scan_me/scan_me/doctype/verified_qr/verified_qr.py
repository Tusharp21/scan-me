# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class VerifiedQR(Document):
	pass


@frappe.whitelist()
def check_button_required(doctype, docname):
	"""Check if 'Generate Verified QR' button should be shown for the given doctype."""
	settings = frappe.get_single("Scan Me Settings")
	allowed_doctypes = [d.ref_doctype for d in settings.get("ref_doctype_info") if d.enable]

	if doctype not in allowed_doctypes:
		return False

	if check_existing_verified_qr(doctype, docname, frappe.session.user):
		return False

	return True


@frappe.whitelist()
def check_signature_required(doctype):
	"""Check signature required."""
	settings = frappe.get_single("Scan Me Settings")
	allowed_doctypes = [d.ref_doctype for d in settings.get("ref_doctype_info") if d.signature_required]
	return doctype in allowed_doctypes


@frappe.whitelist()
def check_existing_verified_qr(doctype, docname, signed_by):
	"""Get existing Verified QR for the given document and signer."""
	criteria = {"ref_doctype": doctype, "ref_docname": docname, "signed_by": signed_by}
	exist = frappe.db.exists("Verified QR", criteria)
	return exist
