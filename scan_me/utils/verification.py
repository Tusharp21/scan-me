"""Verification primitives for Scan Me.

Content hashing, QR payload encoding/decoding, and a single source of truth
for the signing/lock toggles held in ``Scan Me Settings``.
"""

import hashlib
import hmac
import json
from decimal import Decimal

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

# Float/Decimal values are rounded to this many decimal places before hashing
# so tiny representation drift (e.g. ``0.1 + 0.2 == 0.30000000000000004``)
# doesn't invalidate an otherwise-identical document. 6 places supports paise/
# cents-level precision while staying well inside float64's stable range.
HASH_NUMERIC_PRECISION = 6

QR_SEPARATOR = "|"

# site_config.json key that stores the per-site HMAC secret used to sign
# QR payloads. Kept out of the database so a DB-only leak can't forge QRs,
# and out of version control because site_config is per-install.
QR_SECRET_CONF_KEY = "scan_me_qr_secret"


def _get_qr_signing_secret():
	"""Return the per-site HMAC secret, creating one on first use.

	Mirrors Frappe's own ``encryption_key`` pattern: we generate a 256-bit
	random token the first time we need it and persist it to
	``site_config.json`` via ``update_site_config`` (which takes a filelock,
	so concurrent workers don't race). Subsequent calls just read it back
	from ``frappe.conf``.
	"""
	secret = frappe.conf.get(QR_SECRET_CONF_KEY)
	if secret:
		return secret

	from frappe.installer import update_site_config

	secret = frappe.generate_hash(length=64)
	update_site_config(QR_SECRET_CONF_KEY, secret, validate=False)
	# Refresh the in-memory conf so the rest of this request sees the new key
	# without having to reload from disk.
	frappe.conf[QR_SECRET_CONF_KEY] = secret
	return secret


def _sign_qr_body(body):
	"""HMAC-SHA256 over the unsigned portion of the payload, returned as hex."""
	secret = _get_qr_signing_secret().encode("utf-8")
	return hmac.new(secret, body.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_doc_hash(doctype, name):
	"""Return a hex sha256 of the document content.

	Meta fields that change independently of the doc body are stripped before
	hashing and numeric values are rounded to a fixed precision so float
	representation drift doesn't trigger false ``tampered`` results. Child
	tables are serialized in their existing (idx-ordered) list order, which
	Frappe's ``as_dict`` preserves via ``ORDER BY idx`` on child loads.
	"""
	doc = frappe.get_doc(doctype, name)
	data = doc.as_dict(convert_dates_to_str=True)
	cleaned = _normalize_for_hash(data)
	serialized = json.dumps(cleaned, sort_keys=True, default=str)
	return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_for_hash(value):
	"""Recursively strip meta fields and canonicalize numeric values."""
	if isinstance(value, dict):
		return {k: _normalize_for_hash(v) for k, v in value.items() if k not in META_FIELDS}
	if isinstance(value, list):
		return [_normalize_for_hash(v) for v in value]
	if isinstance(value, bool):
		# bool is a subclass of int — keep it as a boolean so JSON emits
		# true/false rather than 1/0 and we don't collide with int values.
		return value
	if isinstance(value, float):
		return round(value, HASH_NUMERIC_PRECISION)
	if isinstance(value, Decimal):
		# Serialize as a fixed-precision string so trailing-zero differences
		# (Decimal("1.50") vs Decimal("1.5")) produce the same output.
		quantum = Decimal(1).scaleb(-HASH_NUMERIC_PRECISION)
		return format(value.quantize(quantum), "f")
	return value


def build_qr_payload(unique_id, content_hash=None):
	"""Format the string that goes into the QR image.

	The emitted payload is always three segments: ``uuid|hash|sig``. The hash
	segment is empty when content hashing is disabled. ``sig`` is an
	HMAC-SHA256 over ``uuid|hash`` using the per-site secret so the payload
	can be authenticated offline and ``parse_qr_payload`` can reject forged
	QRs before a DB lookup.
	"""
	body = f"{unique_id}{QR_SEPARATOR}{content_hash or ''}"
	sig = _sign_qr_body(body)
	return f"{body}{QR_SEPARATOR}{sig}"


def parse_qr_payload(raw):
	"""Reverse of build_qr_payload. Returns ``(unique_id, content_hash, sig)``.

	Accepts three payload shapes so QRs printed before HMAC signing was
	introduced still scan:
	- ``uuid|hash|sig`` — current format, sig verified against HMAC secret.
	- ``uuid|hash`` — legacy signed-content payload, ``sig`` returned as None.
	- ``uuid`` — legacy UUID-only payload, ``sig`` and hash returned as None.

	Callers MUST treat a None sig as "legacy, trust only the DB": the
	``content_hash`` segment from legacy payloads is not authenticated and
	must never be used as a fallback for tamper detection.
	"""
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
	"""Timing-safe check that ``sig`` is the HMAC of ``uuid|hash``.

	Returns False for any missing input so callers can collapse
	"no signature" and "bad signature" into a single reject path.
	"""
	if not sig or not unique_id:
		return False
	expected = _sign_qr_body(f"{unique_id}{QR_SEPARATOR}{content_hash or ''}")
	return hmac.compare_digest(expected, sig)


# ---------------------------------------------------------------------------
# Stored content-hash format
# ---------------------------------------------------------------------------
# Plain SHA-256 of a document is deterministic, so two records with identical
# content produce identical stored values — a DB dump lets an attacker
# correlate "which signed documents have the same body". The v1 format wraps
# the plain hash in an HMAC keyed by the per-site secret and salted with the
# record's identity (doctype + docname + signed_by), so:
#   - Two identical documents signed by different users/records store
#     different values → no cross-doc correlation from a DB leak.
#   - The HMAC secret lives in site_config.json (see _get_qr_signing_secret),
#     not the DB — so a DB-only dump cannot produce valid-looking stored
#     values even if the attacker knows the target doc's content.
#
# Legacy records inserted before this format existed are bare 64-hex strings;
# verify_stored_hash detects them by the absence of the version prefix and
# falls back to a plain compare so existing QRs keep verifying forever. An
# admin can upgrade a legacy record to v1 by re-signing the document.
HASH_VERSION_PREFIX = "v1:"


def _content_hash_hmac_body(doctype, name, signed_by, plain_hash):
	"""Compose the HMAC input for a stored content hash.

	Binding in ``doctype``, ``name`` and ``signed_by`` is what prevents two
	records with identical document content from producing the same stored
	value. Empty values are normalised to the empty string so ``None`` vs
	``""`` doesn't cause a stable/unstable flip between sign and verify.
	"""
	return QR_SEPARATOR.join([plain_hash or "", doctype or "", name or "", signed_by or ""])


def compute_stored_hash(doctype, name, signed_by):
	"""HMAC-wrap the document's content hash for storage on a Verified QR.

	Always returns the v1 format. Callers that want the raw SHA-256 (for
	display or for other comparisons) should call :func:`compute_doc_hash`.
	"""
	plain = compute_doc_hash(doctype, name)
	secret = _get_qr_signing_secret().encode("utf-8")
	body = _content_hash_hmac_body(doctype, name, signed_by, plain).encode("utf-8")
	mac = hmac.new(secret, body, hashlib.sha256).hexdigest()
	return f"{HASH_VERSION_PREFIX}{mac}"


def verify_stored_hash(stored_value, doctype, name, signed_by, current_plain=None):
	"""Check a stored content_hash against the current state of (doctype, name).

	``current_plain`` is an optional optimisation: callers that already
	computed ``compute_doc_hash(doctype, name)`` for display pass it in so we
	don't re-read the document a second time. Pass ``None`` to compute
	internally.

	Returns True when the stored value matches. Returns False when it doesn't
	or when the current document can't be read (fail-closed — we'd rather
	flag a broken doc as tampered than silently pass it).
	"""
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

	# Legacy: bare sha256 stored before the v1 format existed.
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
	"""Return the set of doctypes enabled for Verified QR / signed PDF rendering.

	Pulled from the ``ref_doctype_info`` child table on Scan Me Settings.
	Rows with ``enable`` unticked are excluded — lets an admin keep a doctype
	in the table without activating it.
	"""
	settings = frappe.get_single("Scan Me Settings")
	return {d.ref_doctype for d in (settings.get("ref_doctype_info") or []) if d.enable}


def assert_allowed_doctype(doctype):
	"""Raise ``frappe.PermissionError`` if ``doctype`` isn't on the allowlist.

	Single source of truth for the "is this doctype in Scan Me Settings"
	gate — used by every endpoint that applies QR / signature / PAdES to a
	document so the allowlist can't be bypassed from a different code path.
	"""
	if doctype not in get_allowed_doctypes():
		frappe.throw(
			frappe._(
				"'{0}' is not enabled for Scan Me. Configure it under 'Allowed Documents' in Scan Me Settings."
			).format(doctype),
			frappe.PermissionError,
		)
