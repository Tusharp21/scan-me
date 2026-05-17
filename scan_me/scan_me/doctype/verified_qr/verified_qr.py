# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from scan_me.utils.verification import get_signing_settings


class VerifiedQR(Document):
	def validate(self):
		# Absolute lock on updates once inserted; no override role.
		if self.is_new():
			return
		if get_signing_settings()["lock_verified_qr"]:
			frappe.throw(
				frappe._("Verified QR records are locked. They cannot be modified once created."),
				frappe.PermissionError,
			)

	def on_trash(self):
		if get_signing_settings()["lock_verified_qr"]:
			frappe.throw(
				frappe._("Verified QR records are locked. They cannot be deleted."),
				frappe.PermissionError,
			)


@frappe.whitelist(allow_guest=False)
def check_button_required(doctype, docname):
	"""Show 'Generate Verified QR' button? Honours allowlist, write perm, and signer rules."""
	settings = frappe.get_single("Scan Me Settings")
	allowed_doctypes = [d.ref_doctype for d in settings.get("ref_doctype_info") if d.enable]

	if doctype not in allowed_doctypes:
		return False

	# Write-perm gate stops low-role users from enumerating signed docs.
	if not frappe.has_permission(doctype, "write", docname):
		return False

	signing = get_signing_settings()
	if signing["allow_multiple_signers"]:
		if check_existing_verified_qr(doctype, docname, frappe.session.user):
			return False
	else:
		if frappe.db.exists("Verified QR", {"ref_doctype": doctype, "ref_docname": docname}):
			return False

	return True


@frappe.whitelist(allow_guest=False)
def check_signature_required(doctype):
	"""True if this doctype requires a signature image; gated by write perm to block enumeration."""
	if not frappe.has_permission(doctype, "write"):
		frappe.throw(frappe._("Not permitted."), frappe.PermissionError)
	settings = frappe.get_single("Scan Me Settings")
	allowed_doctypes = [d.ref_doctype for d in settings.get("ref_doctype_info") if d.signature_required]
	return doctype in allowed_doctypes


@frappe.whitelist(allow_guest=False)
def check_existing_verified_qr(doctype, docname, signed_by):
	"""Verified QR name for (doctype, docname, signed_by); write-perm gated to block enumeration."""
	if not frappe.has_permission(doctype, "write", docname):
		frappe.throw(frappe._("Not permitted."), frappe.PermissionError)
	criteria = {"ref_doctype": doctype, "ref_docname": docname, "signed_by": signed_by}
	return frappe.db.exists("Verified QR", criteria)
