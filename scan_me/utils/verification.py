"""Verification primitives for Scan Me.

Content hashing, QR payload encoding/decoding, and a single source of truth
for the signing/lock toggles held in ``Scan Me Settings``.
"""

import hashlib
import json

import frappe

# Fields that change independently of content — excluded from the hash so an
# unrelated touch (re-opening, auto-comments, liked-by) doesn't invalidate a
# signature.
META_FIELDS = {
	"modified",
	"modified_by",
	"creation",
	"owner",
	"_liked_by",
	"_comments",
	"_user_tags",
	"_assign",
	"idx",
}

QR_SEPARATOR = "|"


def compute_doc_hash(doctype, name):
	"""Return a hex sha256 of the document content.

	Meta fields that change independently of the doc body are stripped before
	hashing. Child tables are included in a deterministic order via
	``json.dumps(..., sort_keys=True)``.
	"""
	doc = frappe.get_doc(doctype, name)
	data = doc.as_dict(convert_dates_to_str=True)
	cleaned = _strip_meta(data)
	serialized = json.dumps(cleaned, sort_keys=True, default=str)
	return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _strip_meta(value):
	if isinstance(value, dict):
		return {k: _strip_meta(v) for k, v in value.items() if k not in META_FIELDS}
	if isinstance(value, list):
		return [_strip_meta(v) for v in value]
	return value


def build_qr_payload(unique_id, content_hash=None):
	"""Format the string that goes into the QR image."""
	if content_hash:
		return f"{unique_id}{QR_SEPARATOR}{content_hash}"
	return unique_id


def parse_qr_payload(raw):
	"""Reverse of build_qr_payload. Returns (unique_id, content_hash_or_None)."""
	if not raw:
		return "", None
	if QR_SEPARATOR in raw:
		uid, _, h = raw.partition(QR_SEPARATOR)
		return uid.strip(), (h.strip() or None)
	return raw.strip(), None


def get_signing_settings():
	"""Return the Verification & Signing toggles as a plain dict."""
	s = frappe.get_single("Scan Me Settings")
	return {
		"allow_multiple_signers": bool(s.get("allow_multiple_signers")),
		"enable_content_hash": bool(s.get("enable_content_hash")),
		"lock_verified_qr": bool(s.get("lock_verified_qr")),
		"reject_client_signature_data": bool(s.get("reject_client_signature_data")),
		"enable_pades_signing": bool(s.get("enable_pades_signing")),
	}
