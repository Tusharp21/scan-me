# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
import re
import uuid

import frappe

from scan_me.utils.verification import assert_allowed_doctype, compute_stored_hash, get_signing_settings

# Client-supplied signature: PNG/JPEG data URI, up to ~2 MB after base64.
SIGNATURE_DATA_URI_RE = re.compile(r"^data:image/(png|jpeg|jpg);base64,[A-Za-z0-9+/=]+$")
MAX_SIGNATURE_BYTES = 2 * 1024 * 1024


def _validate_client_signature(signature_data):
	"""Reject signature payloads that aren't PNG/JPEG data URIs or are too large."""
	if not signature_data:
		return None
	if len(signature_data) > MAX_SIGNATURE_BYTES:
		frappe.throw(frappe._("Signature image is too large (max 2 MB)."))
	if not SIGNATURE_DATA_URI_RE.match(signature_data):
		frappe.throw(frappe._("Signature must be a base64-encoded PNG or JPEG data URI."))
	return signature_data


def _lookup_user_signature(user):
	"""User signature image from one of the admin-added Custom Fields, or None."""
	user_meta = frappe.get_meta("User")
	for field in ("user_signature", "signature", "signature_image"):
		if user_meta.has_field(field):
			val = frappe.db.get_value("User", user, field)
			if val:
				return val
	return None


@frappe.whitelist(allow_guest=False)
def generate_verified_qr(doctype, docname, signature_data=None):
	"""Create a Verified QR for a document, honouring Scan Me Settings toggles."""

	# Signing requires WRITE perm (not just read); Verified QR insert below
	# uses ignore_permissions, so this gate is the real access check.
	if not frappe.has_permission(doctype, "write", docname):
		frappe.throw(
			frappe._("You do not have permission to sign this document."),
			frappe.PermissionError,
		)

	assert_allowed_doctype(doctype)

	signed_by = frappe.session.user
	signed_on = frappe.utils.now()

	# Block Administrator: it can impersonate, so signing as it breaks audit.
	if frappe.session.user == "Administrator":
		frappe.throw(frappe._("Administrator cannot sign documents."))

	signing = get_signing_settings()

	if signing["allow_multiple_signers"]:
		# Multi-signer: reject only if THIS user already signed.
		existing_qr = frappe.db.get_value(
			"Verified QR",
			{"ref_doctype": doctype, "ref_docname": docname, "signed_by": signed_by},
			"name",
		)
	else:
		# Single-signer: reject if any QR exists.
		existing_qr = frappe.db.get_value(
			"Verified QR",
			{"ref_doctype": doctype, "ref_docname": docname},
			"name",
		)

	if existing_qr:
		return {
			"message": "Verified QR already exists for this document.",
			"existing": True,
		}

	# Prefer the User profile signature over client-supplied: stops a caller
	# from forging someone else's signature via signature_data.
	final_signature = _lookup_user_signature(signed_by)
	if not final_signature and not signing["reject_client_signature_data"] and signature_data:
		final_signature = _validate_client_signature(signature_data)

	content_hash = (
		compute_stored_hash(doctype, docname, signed_by) if signing["enable_content_hash"] else None
	)

	# Stamp at sign time so admin-default changes don't retroactively expire QRs.
	validity_days = frappe.db.get_single_value("Scan Me Settings", "default_qr_validity_days") or 0
	try:
		validity_days = int(validity_days)
	except (TypeError, ValueError):
		validity_days = 0
	valid_until = frappe.utils.add_days(signed_on, validity_days) if validity_days > 0 else None

	unique_id = str(uuid.uuid4())
	qr_master = frappe.get_doc(
		{
			"doctype": "Verified QR",
			"ref_doctype": doctype,
			"ref_docname": docname,
			"unique_id": unique_id,
			"created_on": frappe.utils.now(),
			"signed_by": signed_by,
			"signed_on": signed_on,
			**({"signature": final_signature} if final_signature else {}),
			**({"content_hash": content_hash} if content_hash else {}),
			**({"valid_until": valid_until} if valid_until else {}),
		}
	)
	# ignore_permissions intentional: real access gate is the has_permission
	# check at top. Signers get row-scoped read via if_owner on Verified QR.
	qr_master.insert(ignore_permissions=True)

	return {
		"message": "Verified QR created successfully!",
		"existing": False,
		"unique_id": unique_id,
		"content_hash": content_hash,
		"valid_until": valid_until,
	}
