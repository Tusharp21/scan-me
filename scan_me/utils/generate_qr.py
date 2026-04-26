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
	"""Return the handwritten signature image stored on the User profile, if any.

	Frappe's User doctype has no native signature field; admins add a Custom
	Field named one of ``user_signature``, ``signature``, or ``signature_image``.
	Returns the first non-empty value, or ``None`` if none exist.
	"""
	user_meta = frappe.get_meta("User")
	for field in ("user_signature", "signature", "signature_image"):
		if user_meta.has_field(field):
			val = frappe.db.get_value("User", user, field)
			if val:
				return val
	return None


@frappe.whitelist(allow_guest=False)
def generate_verified_qr(doctype, docname, signature_data=None):
	"""Create a Verified QR for a document.

	Respects the Verification & Signing toggles in Scan Me Settings:
	- allow_multiple_signers: if off, a second Verified QR for the same doc is rejected.
	- enable_content_hash: sha256 of doc content is stored on the record.
	- reject_client_signature_data: ignores the passed signature, reads User.signature_image.
	"""

	# Signing is a state-changing attestation — require explicit write
	# permission on the target document, not just read. This closes the
	# loophole where a read-only user could create a Verified QR via this
	# endpoint (Verified QR itself is System-Manager-only and gets inserted
	# with ignore_permissions below, so the gate has to live here).
	if not frappe.has_permission(doctype, "write", docname):
		frappe.throw(
			frappe._("You do not have permission to sign this document."),
			frappe.PermissionError,
		)

	assert_allowed_doctype(doctype)

	signed_by = frappe.session.user
	signed_on = frappe.utils.now()

	# Administrator is blocked to keep the audit trail honest — Administrator
	# can log in as anyone, so attributing a signature to "Administrator"
	# would be meaningless. Real signers must use a named account.
	if frappe.session.user == "Administrator":
		frappe.throw(frappe._("Administrator cannot sign documents."))

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
	# Always prefer the signer's stored signature on the User profile, even
	# when the admin allows client-supplied signatures. This closes a forgery
	# vector: otherwise a client could submit someone else's signature image
	# via signature_data and it would be stored as ``signed_by``'s. Client
	# data is only used when (a) the user has no stored signature *and*
	# (b) the admin has not enabled reject_client_signature_data.
	final_signature = _lookup_user_signature(signed_by)
	if not final_signature and not signing["reject_client_signature_data"] and signature_data:
		final_signature = _validate_client_signature(signature_data)

	# --- content hash ---------------------------------------------------
	# compute_stored_hash returns the HMAC-wrapped v1 format so a DB leak
	# alone can't be used to correlate identical documents across records
	# or forge valid-looking hashes without the per-site secret.
	content_hash = (
		compute_stored_hash(doctype, docname, signed_by) if signing["enable_content_hash"] else None
	)

	# --- expiry ---------------------------------------------------------
	# Stamped onto the record at sign time and NOT recomputed later, so
	# changing the admin setting doesn't retroactively invalidate QRs that
	# were issued under the old policy. 0 (or unset) means "never expires".
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
	# ignore_permissions is intentional: Verified QR is a ledger whose
	# create-permission isn't the real access gate. The real gate is the
	# frappe.has_permission(doctype, "write", docname) check at the top of
	# this function — a caller who can't write the target doc is rejected
	# before we get here. Signers still receive row-scoped read access to
	# their own records via the Desk User / if_owner permission row on the
	# Verified QR doctype (owner == frappe.session.user == signed_by at
	# insert time, so if_owner correctly matches the signer).
	qr_master.insert(ignore_permissions=True)

	return {
		"message": "Verified QR created successfully!",
		"existing": False,
		"unique_id": unique_id,
		"content_hash": content_hash,
		"valid_until": valid_until,
	}
