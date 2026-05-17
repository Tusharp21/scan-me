"""Verification primitives: content hashing, QR payload codec, signing toggles."""

import hashlib
import hmac
import json
from decimal import Decimal

import frappe

# Stripped before hashing so unrelated touches (comments, likes) don't invalidate sigs.
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

# Rounds floats before hashing so 0.1+0.2 representation drift doesn't false-tamper.
HASH_NUMERIC_PRECISION = 6

QR_SEPARATOR = "|"

# Per-site HMAC secret in site_config.json: out of DB (DB leak can't forge QRs)
# and out of VCS (site_config is per-install).
QR_SECRET_CONF_KEY = "scan_me_qr_secret"


def _get_qr_signing_secret():
	"""Lazily generate/persist a per-site HMAC secret; mirrors Frappe's encryption_key."""
	secret = frappe.conf.get(QR_SECRET_CONF_KEY)
	if secret:
		return secret

	from frappe.installer import update_site_config

	secret = frappe.generate_hash(length=64)
	update_site_config(QR_SECRET_CONF_KEY, secret, validate=False)
	frappe.conf[QR_SECRET_CONF_KEY] = secret
	return secret


def _sign_qr_body(body):
	"""HMAC-SHA256 hex over the unsigned portion of the payload."""
	secret = _get_qr_signing_secret().encode("utf-8")
	return hmac.new(secret, body.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_doc_hash(doctype, name):
	"""Hex sha256 of doc content, with meta fields stripped and numerics canonicalized."""
	doc = frappe.get_doc(doctype, name)
	data = doc.as_dict(convert_dates_to_str=True)
	cleaned = _normalize_for_hash(data)
	serialized = json.dumps(cleaned, sort_keys=True, default=str)
	return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_for_hash(value):
	"""Recursively strip meta fields and canonicalize numerics."""
	if isinstance(value, dict):
		return {k: _normalize_for_hash(v) for k, v in value.items() if k not in META_FIELDS}
	if isinstance(value, list):
		return [_normalize_for_hash(v) for v in value]
	if isinstance(value, bool):
		# bool subclasses int — preserve so JSON emits true/false, not 1/0.
		return value
	if isinstance(value, float):
		return round(value, HASH_NUMERIC_PRECISION)
	if isinstance(value, Decimal):
		# Fixed-precision string so Decimal("1.50") == Decimal("1.5") output.
		quantum = Decimal(1).scaleb(-HASH_NUMERIC_PRECISION)
		return format(value.quantize(quantum), "f")
	return value


def build_qr_payload(unique_id, content_hash=None):
	"""Format QR string as ``uuid|hash|sig``; sig authenticates offline pre-DB-lookup."""
	body = f"{unique_id}{QR_SEPARATOR}{content_hash or ''}"
	sig = _sign_qr_body(body)
	return f"{body}{QR_SEPARATOR}{sig}"


def parse_qr_payload(raw):
	"""Return (uuid, hash, sig). None sig = legacy payload — DO NOT trust its hash."""
	if not raw:
		return "", None, None
	parts = raw.split(QR_SEPARATOR)
	if len(parts) >= 3:
		uid, h, sig = parts[0], parts[1], QR_SEPARATOR.join(parts[2:])
		return uid.strip(), (h.strip() or None), (sig.strip() or None)
	if len(parts) == 2:
		uid, h = parts
		return uid.strip(), (h.strip() or None), None
	return raw.strip(), None, None


def verify_qr_signature(unique_id, content_hash, sig):
	"""Timing-safe HMAC check; False on missing input so callers collapse reject paths."""
	if not sig or not unique_id:
		return False
	expected = _sign_qr_body(f"{unique_id}{QR_SEPARATOR}{content_hash or ''}")
	return hmac.compare_digest(expected, sig)


# Stored hash v1: HMAC keyed by site secret + salted by (doctype,name,signed_by).
# Blocks cross-doc correlation and DB-only forgery (secret lives in site_config).
# Legacy records (bare 64-hex) still verify via plain compare in verify_stored_hash.
HASH_VERSION_PREFIX = "v1:"


def _content_hash_hmac_body(doctype, name, signed_by, plain_hash):
	"""HMAC input bound to (doctype,name,signed_by) so identical docs hash differently."""
	return QR_SEPARATOR.join([plain_hash or "", doctype or "", name or "", signed_by or ""])


def compute_stored_hash(doctype, name, signed_by):
	"""HMAC-wrap doc content hash (v1 format) for Verified QR storage."""
	plain = compute_doc_hash(doctype, name)
	secret = _get_qr_signing_secret().encode("utf-8")
	body = _content_hash_hmac_body(doctype, name, signed_by, plain).encode("utf-8")
	mac = hmac.new(secret, body, hashlib.sha256).hexdigest()
	return f"{HASH_VERSION_PREFIX}{mac}"


def verify_stored_hash(stored_value, doctype, name, signed_by, current_plain=None):
	"""Check stored content_hash vs current doc. Fail-closed: unreadable doc returns False."""
	if not stored_value:
		return True  # nothing stored → nothing to contradict

	if current_plain is None:
		try:
			current_plain = compute_doc_hash(doctype, name)
		except Exception:
			return False

	if stored_value.startswith(HASH_VERSION_PREFIX):
		expected_mac = stored_value[len(HASH_VERSION_PREFIX) :]
		secret = _get_qr_signing_secret().encode("utf-8")
		body = _content_hash_hmac_body(doctype, name, signed_by, current_plain).encode("utf-8")
		actual_mac = hmac.new(secret, body, hashlib.sha256).hexdigest()
		return hmac.compare_digest(expected_mac, actual_mac)

	# Legacy: bare sha256 stored before v1 format.
	return hmac.compare_digest(stored_value, current_plain)


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


def get_allowed_doctypes():
	"""Set of enabled doctypes from Scan Me Settings → ref_doctype_info."""
	settings = frappe.get_single("Scan Me Settings")
	return {d.ref_doctype for d in (settings.get("ref_doctype_info") or []) if d.enable}


def assert_allowed_doctype(doctype):
	"""Single source of truth gate — raise PermissionError if doctype not allowlisted."""
	if doctype not in get_allowed_doctypes():
		frappe.throw(
			frappe._(
				"'{0}' is not enabled for Scan Me. Configure it under 'Allowed Documents' in Scan Me Settings."
			).format(doctype),
			frappe.PermissionError,
		)
