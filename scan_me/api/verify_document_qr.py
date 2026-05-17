# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
import hashlib

import frappe
from frappe.rate_limiter import rate_limit

from scan_me.utils.verification import (
	compute_doc_hash,
	parse_qr_payload,
	verify_qr_signature,
	verify_stored_hash,
)

# Per-UUID throttle on top of the IP-based decorator: blocks distributed-proxy
# harvesting of a single leaked UUID. 60/hr well above legit rescan traffic.
UUID_RATE_LIMIT_WINDOW_SECONDS = 60 * 60
UUID_RATE_LIMIT_PER_WINDOW = 60


def _uuid_rate_limit_ok(scanned_uuid):
	"""Per-UUID counter; key is hashed so a cache dump doesn't leak valid UUIDs."""
	digest = hashlib.sha256(scanned_uuid.encode("utf-8")).hexdigest()[:16]
	key = f"scan_me:verify:uuid:{digest}"
	count = (frappe.cache.get_value(key) or 0) + 1
	frappe.cache.set_value(key, count, expires_in_sec=UUID_RATE_LIMIT_WINDOW_SECONDS)
	return count <= UUID_RATE_LIMIT_PER_WINDOW


# Settings tier → fields authenticated readers see. Guests and non-readers
# are hard-capped to GUEST_ALLOWED_FIELDS regardless of this setting.
DETAIL_LEVELS = {
	"Minimal": {"date_only"},
	"Standard": {"doctype", "docname", "timestamp", "signer_name", "unique_id"},
	"Full": {"doctype", "docname", "timestamp", "signer_name", "unique_id", "hashes"},
}

# Hard cap for guests / users without read perm — prevents leaked-UUID
# enumeration of staff names, doc-series IDs and timestamps.
GUEST_ALLOWED_FIELDS = {"date_only"}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="verify_qr", limit=30, seconds=60)
def verify_document_qr(uuid=None):
	"""Public QR verify endpoint. POST-only blocks silent cross-origin GET probes
	via <img>/<script>/<iframe>; guests get hard-capped fields regardless of tier."""
	raw = uuid or frappe.form_dict.get("uuid")
	if not raw:
		return {"status": "error", "message": frappe._("No QR data provided")}

	scanned_uuid, scanned_hash, scanned_sig = parse_qr_payload(raw)
	if not scanned_uuid:
		return {"status": "error", "message": frappe._("Malformed QR payload")}

	# Signed QRs MUST validate; legacy unsigned QRs pass but their scanned_hash
	# is ignored below (only DB content_hash is trusted for tamper detection).
	if scanned_sig is not None and not verify_qr_signature(scanned_uuid, scanned_hash, scanned_sig):
		return {
			"status": "invalid",
			"title": frappe._("Unable to Validate"),
			"message": frappe._(
				"The provided QR code is not associated with any approved record. "
				"Kindly recheck the document and attempt verification again."
			),
		}

	# Throttle BEFORE DB lookup; collapse to generic invalid so "over limit"
	# is indistinguishable from "bad UUID".
	if not _uuid_rate_limit_ok(scanned_uuid):
		return {
			"status": "invalid",
			"title": frappe._("Unable to Validate"),
			"message": frappe._(
				"The provided QR code is not associated with any approved record. "
				"Kindly recheck the document and attempt verification again."
			),
		}

	qr = frappe.db.get_value(
		"Verified QR",
		{"unique_id": scanned_uuid},
		[
			"ref_doctype",
			"ref_docname",
			"creation",
			"signed_by",
			"signed_on",
			"content_hash",
			"unique_id",
			"valid_until",
		],
		as_dict=True,
	)

	if not qr:
		return {
			"status": "invalid",
			"title": frappe._("Unable to Validate"),
			"message": frappe._(
				"The provided QR code is not associated with any approved record. "
				"Kindly recheck the document and attempt verification again."
			),
		}

	# Expiry: per-record stamp set at sign time so admin-default changes don't
	# retroactively invalidate old QRs. Absent valid_until = never expires.
	if qr.valid_until and frappe.utils.getdate(qr.valid_until) < frappe.utils.getdate():
		return {
			"status": "expired",
			"title": frappe._("Verification Expired"),
			"message": frappe._(
				"This QR code was valid at signing time but has since expired. "
				"Please request a fresh copy of the document from the issuer."
			),
		}

	# Tamper check: only DB content_hash is trusted (scanned_hash could be
	# forged on legacy unsigned payloads). verify_stored_hash picks v1/plain.
	tampered = False
	current_hash = None
	stored_hash = qr.content_hash
	if stored_hash:
		try:
			current_hash = compute_doc_hash(qr.ref_doctype, qr.ref_docname)
		except Exception:
			current_hash = None
		if current_hash and not verify_stored_hash(
			stored_hash, qr.ref_doctype, qr.ref_docname, qr.signed_by, current_plain=current_hash
		):
			tampered = True

	# Configured tier is the MAX for authenticated readers; everyone else is
	# capped to GUEST_ALLOWED_FIELDS to block leaked-UUID enumeration.
	level = frappe.db.get_single_value("Scan Me Settings", "public_verify_detail") or "Standard"
	configured = DETAIL_LEVELS.get(level, DETAIL_LEVELS["Standard"])

	is_guest = frappe.session.user == "Guest"
	can_read_ref = False
	if not is_guest:
		try:
			can_read_ref = bool(frappe.has_permission(qr.ref_doctype, "read", qr.ref_docname))
		except Exception:
			can_read_ref = False  # fail closed

	# Not an intersection: guest cap is a fixed fallback so guests still see
	# the date even when configured tier doesn't include date_only.
	allowed = configured if can_read_ref else GUEST_ALLOWED_FIELDS

	status = "tampered" if tampered else "valid"
	body = {
		"status": status,
		"title": (
			frappe._("Document Modified After Signing") if tampered else frappe._("Document Authenticated")
		),
		"message": (
			frappe._(
				"The QR is genuine, but the document content has changed since it was signed. "
				"The signature is no longer valid for the current content."
			)
			if tampered
			else frappe._("This document is authentic and has not been modified since signing.")
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
	if "unique_id" in allowed:
		body["unique_id"] = qr.unique_id
	if "hashes" in allowed and tampered:
		body["stored_hash"] = stored_hash
		body["current_hash"] = current_hash

	return body
