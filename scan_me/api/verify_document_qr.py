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

# Per-UUID secondary rate limit on top of the decorator's IP-based limit.
# Catches the distributed-proxy attack where a single leaked UUID is probed
# from many IPs — each IP stays under its own IP budget but the UUID itself
# is throttled globally. 60/hr is well above legitimate rescan traffic for
# a given document and low enough that harvesting is slow.
UUID_RATE_LIMIT_WINDOW_SECONDS = 60 * 60
UUID_RATE_LIMIT_PER_WINDOW = 60


def _uuid_rate_limit_ok(scanned_uuid):
	"""Increment a per-UUID counter in Redis and return False when exceeded.

	The cache key hashes the UUID (truncated) instead of using it raw so a
	dump of Redis keys doesn't reveal the set of valid UUIDs in the system.
	"""
	digest = hashlib.sha256(scanned_uuid.encode("utf-8")).hexdigest()[:16]
	key = f"scan_me:verify:uuid:{digest}"
	current = frappe.cache.get(key) or 0
	if not current:
		frappe.cache.setex(key, UUID_RATE_LIMIT_WINDOW_SECONDS, 0)
	count = frappe.cache.incrby(key, 1)
	return count <= UUID_RATE_LIMIT_PER_WINDOW


# Settings value → which response fields authenticated callers can see.
# Guests and users without read permission on the referenced document are
# hard-capped to GUEST_ALLOWED_FIELDS below, regardless of this setting.
DETAIL_LEVELS = {
	"Minimal": {"date_only"},
	"Standard": {"doctype", "docname", "timestamp", "signer_name", "unique_id"},
	"Full": {"doctype", "docname", "timestamp", "signer_name", "unique_id", "hashes"},
}

# Fields a guest (or a user who can't read the referenced doc) is allowed to
# see. Deliberately minimal — the public verify page exists to answer
# "is this paper document authentic?" not to reveal who signed what when.
# Without this cap, a single leaked UUID lets an attacker harvest staff
# names, doc-series IDs and timestamps by enumerating the /verify endpoint.
GUEST_ALLOWED_FIELDS = {"date_only"}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="verify_qr", limit=30, seconds=60)
def verify_document_qr(uuid=None):
	"""Public QR verification endpoint — POST only.

	Response verbosity is gated by ``Scan Me Settings → Public Verify Detail Level``
	*and* by who is calling. Guests — and logged-in users without read
	permission on the referenced document — are hard-capped to status +
	signed-on date, regardless of the admin setting. Only authenticated
	callers who can already read the target doc receive the configured
	tier's richer fields (doctype, docname, signer name, unique_id, hashes).
	Rate-limited to **30 requests per 60 seconds per IP** so leaked-UUID
	harvesting is slow even within the minimal guest response.

	POST-only so third-party pages can't silently probe the endpoint by
	embedding ``<img src="/api/method/...?uuid=X">`` — ``<img>``, ``<script>``,
	``<iframe>`` and ``<link>`` all issue GET, so restricting to POST makes
	cross-origin probing require actual JS the browser will block via CORS.
	Guest sessions have no CSRF token, so Frappe's CSRF check is a no-op
	here (see ``frappe.auth.HTTPRequest.validate_csrf_token``) — no token
	plumbing needed on the public verify page.
	"""
	raw = uuid or frappe.form_dict.get("uuid")
	if not raw:
		return {"status": "error", "message": frappe._("No QR data provided")}

	scanned_uuid, scanned_hash, scanned_sig = parse_qr_payload(raw)
	if not scanned_uuid:
		return {"status": "error", "message": frappe._("Malformed QR payload")}

	# If the QR carries a signature it MUST validate. Legacy QRs printed
	# before HMAC signing was introduced have no sig — those are still
	# accepted, but their scanned_hash is ignored below (we only trust
	# the DB's content_hash for tamper detection).
	if scanned_sig is not None and not verify_qr_signature(scanned_uuid, scanned_hash, scanned_sig):
		return {
			"status": "invalid",
			"title": frappe._("Unable to Validate"),
			"message": frappe._(
				"The provided QR code is not associated with any approved record. "
				"Kindly recheck the document and attempt verification again."
			),
		}

	# Per-UUID throttle — run BEFORE the DB lookup so a brute-force loop
	# doesn't get a free read per probe. Collapsed into the generic invalid
	# response so the attacker can't distinguish "over limit" from "bad UUID".
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

	# --- expiry ---------------------------------------------------------
	# valid_until is the last day (inclusive) the QR is accepted. Absent
	# means "never expires". The signing-date field is intentionally not
	# rechecked here — expiry is evaluated against the per-record stamp
	# captured at sign time so changing the admin default doesn't
	# retroactively invalidate previously issued QRs.
	if qr.valid_until and frappe.utils.getdate(qr.valid_until) < frappe.utils.getdate():
		return {
			"status": "expired",
			"title": frappe._("Verification Expired"),
			"message": frappe._(
				"This QR code was valid at signing time but has since expired. "
				"Please request a fresh copy of the document from the issuer."
			),
		}

	# --- tamper detection ---------------------------------------------
	# Only the DB-stored content_hash is authoritative. We deliberately do
	# NOT fall back to scanned_hash — that value comes from the QR itself
	# and (for legacy unsigned payloads) could be forged to mask tampering.
	# current_hash is computed here (plain sha256) for the response body;
	# verify_stored_hash handles the actual compare — plain vs v1:HMAC
	# is decided by the stored value's prefix, not by the caller.
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

	# --- build response per detail level -----------------------------
	# The admin-configured tier is the *maximum* detail an authenticated user
	# with read permission on the referenced doc can receive. Guests and any
	# user who lacks read permission are hard-capped to GUEST_ALLOWED_FIELDS
	# so the public verify page can't be used to enumerate staff names,
	# doc-series IDs, or signing timestamps via leaked UUIDs.
	level = frappe.db.get_single_value("Scan Me Settings", "public_verify_detail") or "Standard"
	configured = DETAIL_LEVELS.get(level, DETAIL_LEVELS["Standard"])

	is_guest = frappe.session.user == "Guest"
	can_read_ref = False
	if not is_guest:
		try:
			can_read_ref = bool(frappe.has_permission(qr.ref_doctype, "read", qr.ref_docname))
		except Exception:
			# A caller whose role list can't even evaluate permission on the
			# target doctype is treated as a guest — fail closed.
			can_read_ref = False

	# Authenticated + read perm → configured tier. Everyone else → the fixed
	# guest cap (intentionally not an intersection so a Standard/Full-only
	# tier still shows guests the date, rather than nothing).
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
