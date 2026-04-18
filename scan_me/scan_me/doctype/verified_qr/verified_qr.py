# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from scan_me.utils.verification import get_signing_settings


class VerifiedQR(Document):
	def validate(self):
		# Absolute lock on updates once inserted. No override role.
		if self.is_new():
			return
		if get_signing_settings()["lock_verified_qr"]:
			frappe.throw(
				"Verified QR records are locked. They cannot be modified once created.",
				frappe.PermissionError,
			)

	def on_trash(self):
		if get_signing_settings()["lock_verified_qr"]:
			frappe.throw(
				"Verified QR records are locked. They cannot be deleted.",
				frappe.PermissionError,
			)


@frappe.whitelist()
def check_button_required(doctype, docname):
	"""Decide whether to show the 'Generate Verified QR' button on a form.

	Hidden when the doctype isn't allowlisted, or when this user/doc pair
	already has a Verified QR. With multi-signer off, one QR (any user)
	hides the button for everyone.
	"""
	settings = frappe.get_single("Scan Me Settings")
	allowed_doctypes = [d.ref_doctype for d in settings.get("ref_doctype_info") if d.enable]

	if doctype not in allowed_doctypes:
		return False

	signing = get_signing_settings()
	if signing["allow_multiple_signers"]:
		if check_existing_verified_qr(doctype, docname, frappe.session.user):
			return False
	else:
		if frappe.db.exists("Verified QR", {"ref_doctype": doctype, "ref_docname": docname}):
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
