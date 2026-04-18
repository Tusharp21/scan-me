# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
import frappe
from frappe.rate_limiter import rate_limit

from scan_me.utils.verification import compute_doc_hash, parse_qr_payload

# Settings value → which response fields guests are allowed to see.
DETAIL_LEVELS = {
	"Minimal": {"doctype", "date_only"},
	"Standard": {"doctype", "docname", "timestamp", "signer_name", "unique_id"},
	"Full": {"doctype", "docname", "timestamp", "signer_name", "signer_email", "unique_id", "hashes"},
}


@frappe.whitelist(allow_guest=True)
@rate_limit(key="verify_qr", limit=30, seconds=60)
def verify_document_qr(uuid=None):
	"""Public QR verification endpoint.

	Response verbosity is gated by ``Scan Me Settings → Public Verify Detail Level``.
	Defaults to ``Standard`` (doc name + signer full name + timestamp; no email).
	Rate-limited per IP (30 requests / 60 seconds).
	"""
	raw = uuid or frappe.form_dict.get("uuid")
	if not raw:
		return {"status": "error", "message": "No QR data provided"}

	scanned_uuid, scanned_hash = parse_qr_payload(raw)
	if not scanned_uuid:
		return {"status": "error", "message": "Malformed QR payload"}

	qr = frappe.db.get_value(
		"Verified QR",
		{"unique_id": scanned_uuid},
		["ref_doctype", "ref_docname", "creation", "signed_by", "signed_on", "content_hash", "unique_id"],
		as_dict=True,
	)

	if not qr:
		return {
			"status": "invalid",
			"title": "Unable to Validate",
			"message": (
				"The provided QR code is not associated with any approved record. "
				"Kindly recheck the document and attempt verification again."
			),
		}

	# --- tamper detection ---------------------------------------------
	tampered = False
	current_hash = None
	stored_hash = qr.content_hash or scanned_hash
	if stored_hash:
		try:
			current_hash = compute_doc_hash(qr.ref_doctype, qr.ref_docname)
		except Exception:
			current_hash = None
		if current_hash and current_hash != stored_hash:
			tampered = True

	# --- build response per detail level -----------------------------
	level = frappe.db.get_single_value("Scan Me Settings", "public_verify_detail") or "Standard"
	allowed = DETAIL_LEVELS.get(level, DETAIL_LEVELS["Standard"])

	status = "tampered" if tampered else "valid"
	body = {
		"status": status,
		"title": ("Document Modified After Signing" if tampered else "Document Authenticated"),
		"message": (
			"The QR is genuine, but the document content has changed since it was signed. "
			"The signature is no longer valid for the current content."
			if tampered
			else "This document is authentic and has not been modified since signing."
		),
	}

	if "doctype" in allowed:
		body["ref_doctype"] = qr.ref_doctype
	if "docname" in allowed:
		body["ref_docname"] = qr.ref_docname
	if "date_only" in allowed:
		ts = qr.signed_on or qr.creation
		if ts:
			body["signed_on"] = frappe.utils.formatdate(ts, "dd-MMM-yyyy")
	if "timestamp" in allowed:
		ts = qr.signed_on or qr.creation
		if ts:
			body["signed_on"] = frappe.utils.format_datetime(ts, "dd-MMM-yyyy HH:mm:ss")
	if "signer_name" in allowed and qr.signed_by:
		full_name = frappe.db.get_value("User", qr.signed_by, "full_name") or qr.signed_by
		body["signed_by_name"] = full_name
	if "signer_email" in allowed and qr.signed_by:
		body["signed_by_email"] = qr.signed_by
	if "unique_id" in allowed:
		body["unique_id"] = qr.unique_id
	if "hashes" in allowed and tampered:
		body["stored_hash"] = stored_hash
		body["current_hash"] = current_hash

	return body
