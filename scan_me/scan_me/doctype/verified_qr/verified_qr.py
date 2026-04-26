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
	"""Decide whether to show the 'Generate Verified QR' button on a form.

	Hidden when the doctype isn't allowlisted, when the caller can't sign
	the document, or when this user/doc pair already has a Verified QR.
	With multi-signer off, one QR (any user) hides the button for everyone.
	"""
	settings = frappe.get_single("Scan Me Settings")
	allowed_doctypes = [d.ref_doctype for d in settings.get("ref_doctype_info") if d.enable]

	if doctype not in allowed_doctypes:
		return False

	# Gate on write permission. Without this, any logged-in user could poll
	# this endpoint across (doctype, docname) pairs to enumerate which
	# documents have been signed, regardless of whether they can even read
	# those documents. Users without write perm can't sign anyway, so
	# returning False here is the same outcome they'd get from the UI.
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
	"""Return True when signing a doc of this doctype requires a signature image.

	Admin-configured flag from Scan Me Settings. Gated by role-level write
	permission on ``doctype`` so this endpoint can't be used by a low-role
	account as an oracle for "which doctypes require signatures" — that
	mirrors the configuration admin-only perm on Scan Me Settings itself.
	"""
	if not frappe.has_permission(doctype, "write"):
		frappe.throw(frappe._("Not permitted."), frappe.PermissionError)
	settings = frappe.get_single("Scan Me Settings")
	allowed_doctypes = [d.ref_doctype for d in settings.get("ref_doctype_info") if d.signature_required]
	return doctype in allowed_doctypes


@frappe.whitelist(allow_guest=False)
def check_existing_verified_qr(doctype, docname, signed_by):
	"""Return Verified QR name if one exists for (doctype, docname, signed_by).

	Caller must have write permission on the target document. Signing is a
	state-changing attestation, so anyone who wouldn't be allowed to sign
	shouldn't be allowed to probe signing state either — without this gate
	a read-only role could use the ``signed_by`` parameter to enumerate who
	has signed which documents across the system.
	"""
	if not frappe.has_permission(doctype, "write", docname):
		frappe.throw(frappe._("Not permitted."), frappe.PermissionError)
	criteria = {"ref_doctype": doctype, "ref_docname": docname, "signed_by": signed_by}
	return frappe.db.exists("Verified QR", criteria)
