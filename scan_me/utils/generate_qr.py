# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
import re
import uuid

import frappe

from scan_me.utils.verification import compute_doc_hash, get_signing_settings

# Client-supplied signature: PNG/JPEG data URI, up to ~2 MB after base64.
SIGNATURE_DATA_URI_RE = re.compile(r"^data:image/(png|jpeg|jpg);base64,[A-Za-z0-9+/=]+$")
MAX_SIGNATURE_BYTES = 2 * 1024 * 1024


def _validate_client_signature(signature_data):
	"""Reject signature payloads that aren't PNG/JPEG data URIs or are too large."""
	if not signature_data:
		return None
	if len(signature_data) > MAX_SIGNATURE_BYTES:
		frappe.throw("Signature image is too large (max 2 MB).")
	if not SIGNATURE_DATA_URI_RE.match(signature_data):
		frappe.throw("Signature must be a base64-encoded PNG or JPEG data URI.")
	return signature_data


@frappe.whitelist()
def generate_verified_qr(doctype, docname, signature_data=None):
	"""Create a Verified QR for a document.

	Respects the Verification & Signing toggles in Scan Me Settings:
	- allow_multiple_signers: if off, a second Verified QR for the same doc is rejected.
	- enable_content_hash: sha256 of doc content is stored on the record.
	- reject_client_signature_data: ignores the passed signature, reads User.signature_image.
	"""

	if not frappe.has_permission(doctype, "read", docname):
		frappe.throw(
			"You do not have permission to sign this document.",
			frappe.PermissionError,
		)

	settings = frappe.get_single("Scan Me Settings")
	allowed_doctypes = [d.ref_doctype for d in settings.get("ref_doctype_info") if d.enable]
	if doctype not in allowed_doctypes:
		frappe.throw(
			"This doctype is not allowed for Verified QR generation. Please configure it in 'Scan Me Settings'."
		)

	signed_by = frappe.session.user
	signed_on = frappe.utils.now()

	if frappe.session.user == "Administrator":
		frappe.throw("Administrator cannot sign documents.")

	signing = get_signing_settings()

	# --- multi-signer enforcement ---------------------------------------
	if signing["allow_multiple_signers"]:
		# Allow a new QR only if THIS user hasn't already signed.
		existing_qr = frappe.db.get_value(
			"Verified QR",
			{"ref_doctype": doctype, "ref_docname": docname, "signed_by": signed_by},
			"name",
		)
	else:
		# Single-signer: reject if any QR exists, regardless of signer.
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

	# --- signature data source -----------------------------------------
	# Frappe's User doctype has no native visual-signature field. Admins who want
	# server-controlled signatures must add a Custom Field to User — we probe for
	# a few common names. Missing field just leaves the card without a hand image.
	final_signature = None
	if signing["reject_client_signature_data"]:
		user_meta = frappe.get_meta("User")
		for field in ("user_signature", "signature", "signature_image"):
			if user_meta.has_field(field):
				val = frappe.db.get_value("User", signed_by, field)
				if val:
					final_signature = val
					break
	elif signature_data:
		final_signature = _validate_client_signature(signature_data)

	# --- content hash ---------------------------------------------------
	content_hash = compute_doc_hash(doctype, docname) if signing["enable_content_hash"] else None

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
		}
	)
	qr_master.insert(ignore_permissions=True)

	return {
		"message": "Verified QR created successfully!",
		"existing": False,
		"unique_id": unique_id,
		"content_hash": content_hash,
	}
