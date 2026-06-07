# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Admin endpoints for Scan Me cert management — operations that touch
site_config or private files and therefore must run server-side under
System Manager. The PKCS#12 contains a private signing key, so this
module treats every input as hostile: hard size cap, realpath checks
against the site's private files dir, atomic writes, fingerprint-only
audit logging, mandatory cleanup of the temporary upload File doc."""

import datetime as _dt
import os
import shutil
import time

import frappe
from frappe.rate_limiter import rate_limit

# Real PKCS#12 with RSA-3072 + cert is ~3-6 KB. 100 KB is a generous cap
# that still rules out anything plausibly malicious.
_MAX_PFX_BYTES = 100 * 1024
_BACKUP_RETAIN = 3
_AUDIT_PREFIX = "Scan Me: cert admin"


def _site_private_root() -> str:
	return os.path.realpath(os.path.join(frappe.get_site_path(), "private", "files"))


def _safe_pfx_path() -> str:
	"""Path to signing.pfx, hardened against any symlink/traversal that would
	let an attacker write outside the site's private files dir."""
	from scan_me.utils.pades import _pfx_path

	path = os.path.realpath(_pfx_path())
	root = _site_private_root()
	if not (path == os.path.join(root, "scan_me", "signing.pfx") or path.startswith(root + os.sep)):
		frappe.throw(
			frappe._("Refused: certificate path resolved outside private files directory."),
			frappe.ValidationError,
		)
	return path


def _resolve_uploaded_file(file_url: str):
	"""Resolve an uploaded Attach URL to a (File-doc, absolute-path) pair, with
	strict safety checks. Rejects: non-private files, files outside the site's
	private files dir, oversized files. Returns (file_doc, abs_path)."""
	if not isinstance(file_url, str) or not file_url.strip():
		frappe.throw(frappe._("Missing certificate file URL."), frappe.ValidationError)

	# Frappe stores private uploads at /private/files/<name>. Public uploads at
	# /files/<name>. We require private to avoid web-reachable PFX bytes.
	if not file_url.startswith("/private/files/"):
		frappe.throw(
			frappe._("Certificate must be uploaded as a private file."),
			frappe.ValidationError,
		)

	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		frappe.throw(frappe._("Uploaded file not found."), frappe.ValidationError)

	file_doc = frappe.get_doc("File", file_name)
	if not file_doc.is_private:
		frappe.throw(frappe._("Certificate must be a private upload."), frappe.ValidationError)

	# Defence-in-depth: only the System Manager who uploaded it (or another
	# System Manager) may reference it. Since the endpoint already enforces
	# the role, this stays a belt-and-suspenders check on owner attribution.
	if file_doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(frappe._("Refused: file belongs to another user."), frappe.PermissionError)

	abs_path = os.path.realpath(file_doc.get_full_path())
	root = _site_private_root()
	if not abs_path.startswith(root + os.sep):
		frappe.throw(
			frappe._("Refused: file resolves outside private files directory."),
			frappe.ValidationError,
		)
	if not os.path.isfile(abs_path):
		frappe.throw(frappe._("File is missing on disk."), frappe.ValidationError)

	size = os.path.getsize(abs_path)
	if size == 0:
		frappe.throw(frappe._("File is empty."), frappe.ValidationError)
	if size > _MAX_PFX_BYTES:
		frappe.throw(
			frappe._("Certificate file is larger than {0} KB — refused.").format(_MAX_PFX_BYTES // 1024),
			frappe.ValidationError,
		)

	return file_doc, abs_path


def _read_pfx_bytes(file_url: str) -> tuple[bytes, "frappe.model.document.Document"]:
	"""Resolve the upload URL, read bytes with the size cap enforced, return (bytes, File-doc).
	Caller is responsible for wiping the bytes when done."""
	file_doc, abs_path = _resolve_uploaded_file(file_url)
	# nosemgrep: frappe-security-file-traversal — abs_path validated by _resolve_uploaded_file() (realpath + private-root containment)
	with open(abs_path, "rb") as fh:
		pfx_bytes = fh.read(_MAX_PFX_BYTES + 1)
	if len(pfx_bytes) > _MAX_PFX_BYTES:
		frappe.throw(
			frappe._("Certificate file exceeds {0} KB cap.").format(_MAX_PFX_BYTES // 1024),
			frappe.ValidationError,
		)
	return pfx_bytes, file_doc


def _delete_upload(file_doc) -> None:
	"""Remove the temporary File doc (and the underlying file). Best-effort —
	a failure here doesn't unwind the caller's work, but is logged."""
	if not file_doc:
		return
	try:
		frappe.delete_doc("File", file_doc.name, ignore_permissions=True, force=1)
	except Exception:
		frappe.log_error("Scan Me: temp cert upload cleanup failed", frappe.get_traceback())


def _audit(action: str, fingerprint_hex: str | None = None, **extra) -> None:
	"""Per-action audit row in Error Log. Records who/when/what — never password."""
	details = {
		"user": frappe.session.user,
		"action": action,
		"ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
		"fingerprint_sha256_prefix": (fingerprint_hex or "")[:16],
	}
	details.update(extra)
	frappe.log_error(f"{_AUDIT_PREFIX}: {action}", str(details))


def _load_pfx_in_memory(pfx_bytes: bytes, password: bytes):
	"""Decrypts PKCS#12 entirely in memory. Returns (private_key, cert, additional_certs)
	or raises a friendly error. Caller is responsible for wiping inputs."""
	from cryptography.hazmat.primitives.serialization import pkcs12

	try:
		return pkcs12.load_key_and_certificates(pfx_bytes, password)
	except ValueError:
		# cryptography raises ValueError for both wrong password and malformed bytes;
		# treat both as user-facing input errors without leaking which one fired.
		frappe.throw(
			frappe._(
				"Could not decrypt the PKCS#12 bundle. Check that the file is a valid .pfx/.p12 "
				"and that the password is correct."
			),
			frappe.ValidationError,
		)


def _cert_summary(cert) -> dict:
	"""Read-only metadata extracted from an X.509 cert. No private-key fields."""
	from cryptography.hazmat.primitives import hashes

	subject = cert.subject.rfc4514_string()
	issuer = cert.issuer.rfc4514_string()
	is_self_signed = subject == issuer

	try:
		not_before = cert.not_valid_before_utc
		not_after = cert.not_valid_after_utc
	except AttributeError:  # older cryptography
		not_before = cert.not_valid_before.replace(tzinfo=_dt.timezone.utc)
		not_after = cert.not_valid_after.replace(tzinfo=_dt.timezone.utc)

	now = _dt.datetime.now(_dt.timezone.utc)
	days_to_expiry = (not_after - now).days
	is_expired = now > not_after
	not_yet_valid = now < not_before

	digital_signature = False
	content_commitment = False
	try:
		from cryptography.x509.oid import ExtensionOID

		ku = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
		digital_signature = bool(getattr(ku, "digital_signature", False))
		content_commitment = bool(getattr(ku, "content_commitment", False))
	except Exception:
		pass

	fingerprint_sha256 = cert.fingerprint(hashes.SHA256()).hex()

	known_ca_keywords = (
		"sectigo",
		"globalsign",
		"digicert",
		"emudhra",
		"identrust",
		"swisssign",
		"entrust",
		"buypass",
		"docusign",
		"secom",
		"verisign",
		"symantec",
		"trustwave",
		"thawte",
	)
	issuer_lower = issuer.lower()
	ca_hint = next((k for k in known_ca_keywords if k in issuer_lower), None)

	return {
		"subject": subject,
		"issuer": issuer,
		"is_self_signed": is_self_signed,
		"not_before": not_before.isoformat(),
		"not_after": not_after.isoformat(),
		"days_to_expiry": days_to_expiry,
		"is_expired": is_expired,
		"not_yet_valid": not_yet_valid,
		"digital_signature": digital_signature,
		"content_commitment": content_commitment,
		"fingerprint_sha256": fingerprint_sha256,
		"ca_hint": ca_hint,
	}


@frappe.whitelist()
def cert_status_info() -> dict:
	"""Read-only metadata about the currently installed signing cert. Never
	returns the password or any private-key material."""
	frappe.only_for("System Manager")

	from scan_me.utils.pades import PFX_PASSWORD_KEY

	pfx_path = _safe_pfx_path()
	if not os.path.exists(pfx_path):
		return {"installed": False}

	password = frappe.conf.get(PFX_PASSWORD_KEY)
	if not password:
		return {
			"installed": True,
			"readable": False,
			"error": "Password missing from site_config — regenerate or re-upload.",
		}

	try:
		# nosemgrep: frappe-security-file-traversal — pfx_path validated by _safe_pfx_path() (realpath + private-root containment)
		with open(pfx_path, "rb") as fh:
			pfx_bytes = fh.read()
	except OSError as e:
		return {"installed": True, "readable": False, "error": str(e)}

	_, cert, _ = _load_pfx_in_memory(pfx_bytes, password.encode("utf-8"))
	if cert is None:
		return {"installed": True, "readable": False, "error": "PKCS#12 contains no certificate."}

	summary = _cert_summary(cert)
	summary.update({"installed": True, "readable": True})
	return summary


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=3600, key="scan_me_cert_validate")
def validate_cert_upload(file_url: str, password: str) -> dict:
	"""Parse an uploaded PKCS#12 (referenced by Frappe File URL) in memory and
	return cert metadata. Does NOT write to disk and does NOT delete the upload
	— the admin still needs the File available for the Install click that
	follows. Use cancel_cert_upload to clean up if the admin walks away."""
	frappe.only_for("System Manager")

	if not isinstance(password, str) or not password:
		frappe.throw(frappe._("Password is required."), frappe.ValidationError)

	pfx_bytes, _file_doc = _read_pfx_bytes(file_url)
	password_bytes = password.encode("utf-8")
	try:
		_, cert, _ = _load_pfx_in_memory(pfx_bytes, password_bytes)
	finally:
		password_bytes = b"\x00" * len(password_bytes)
		pfx_bytes = b"\x00" * len(pfx_bytes)

	if cert is None:
		frappe.throw(
			frappe._("PKCS#12 contains no certificate. Bundle must include the public cert."),
			frappe.ValidationError,
		)

	summary = _cert_summary(cert)

	warnings = []
	if summary["is_expired"]:
		warnings.append(frappe._("Certificate is already expired — refused on install."))
	elif summary["days_to_expiry"] < 30:
		warnings.append(
			frappe._("Certificate expires in {0} days — plan a renewal soon.").format(
				summary["days_to_expiry"]
			)
		)
	if summary["not_yet_valid"]:
		warnings.append(frappe._("Certificate is not yet valid (not_before is in the future)."))
	if not summary["digital_signature"]:
		warnings.append(
			frappe._(
				"Certificate's Key Usage does not include digital_signature. PAdES signing may be "
				"rejected by some verifiers."
			)
		)
	if summary["is_self_signed"]:
		warnings.append(
			frappe._(
				"This is a self-signed certificate — recipients will still see a yellow "
				'"signer identity unknown" banner in Adobe.'
			)
		)

	return {"ok": True, "cert": summary, "warnings": warnings}


def _rotate_backups(scan_dir: str) -> None:
	"""Keep at most _BACKUP_RETAIN of signing.pfx.<ts>.bak — delete the rest
	(they each contain a private key)."""
	try:
		backups = sorted(
			[f for f in os.listdir(scan_dir) if f.startswith("signing.pfx.") and f.endswith(".bak")],
			reverse=True,
		)
	except FileNotFoundError:
		return
	for stale in backups[_BACKUP_RETAIN:]:
		try:
			os.remove(os.path.join(scan_dir, stale))
		except OSError:
			pass


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=5, seconds=3600, key="scan_me_cert_install")
def install_cert_upload(file_url: str, password: str) -> dict:
	"""Atomically replace signing.pfx + its site_config password with the
	uploaded bundle. Old cert is backed up; rolls back on any error. The temp
	File doc is deleted at the end whether install succeeded or raised."""
	frappe.only_for("System Manager")

	if not isinstance(password, str) or not password:
		frappe.throw(frappe._("Password is required."), frappe.ValidationError)

	from frappe.installer import update_site_config

	from scan_me.utils.pades import PFX_PASSWORD_KEY

	pfx_bytes, file_doc = _read_pfx_bytes(file_url)
	password_bytes = password.encode("utf-8")
	delete_after = True

	try:
		_, cert, _ = _load_pfx_in_memory(pfx_bytes, password_bytes)
		if cert is None:
			frappe.throw(frappe._("PKCS#12 contains no certificate."), frappe.ValidationError)
		summary = _cert_summary(cert)
		if summary["is_expired"]:
			frappe.throw(
				frappe._("Refusing to install an already-expired certificate."),
				frappe.ValidationError,
			)

		dest = _safe_pfx_path()
		scan_dir = os.path.dirname(dest)
		os.makedirs(scan_dir, exist_ok=True)

		old_password = frappe.conf.get(PFX_PASSWORD_KEY)
		backup_path = None
		if os.path.exists(dest):
			ts = int(time.time())
			backup_path = os.path.join(scan_dir, f"signing.pfx.{ts}.bak")
			shutil.copy2(dest, backup_path)
			os.chmod(backup_path, 0o600)

		tmp_path = dest + ".tmp"
		try:
			# nosemgrep: frappe-security-file-traversal — dest validated by _safe_pfx_path()
			with open(tmp_path, "wb") as fh:
				fh.write(pfx_bytes)
				fh.flush()
				os.fsync(fh.fileno())
			os.chmod(tmp_path, 0o600)
			os.replace(tmp_path, dest)
		except Exception:
			if os.path.exists(tmp_path):
				try:
					os.remove(tmp_path)
				except OSError:
					pass
			raise

		try:
			update_site_config(PFX_PASSWORD_KEY, password)
			frappe.conf[PFX_PASSWORD_KEY] = password
		except Exception:
			if backup_path and os.path.exists(backup_path):
				shutil.copy2(backup_path, dest)
				os.chmod(dest, 0o600)
				if old_password:
					update_site_config(PFX_PASSWORD_KEY, old_password)
					frappe.conf[PFX_PASSWORD_KEY] = old_password
			raise

		_rotate_backups(scan_dir)
		_audit(
			"install_cert_upload",
			fingerprint_hex=summary["fingerprint_sha256"],
			subject=summary["subject"][:200],
			issuer=summary["issuer"][:200],
			not_after=summary["not_after"],
		)
		return {
			"ok": True,
			"installed": True,
			"cert": summary,
			"backup_created": bool(backup_path),
		}
	finally:
		password_bytes = b"\x00" * len(password_bytes)
		pfx_bytes = b"\x00" * len(pfx_bytes)
		if delete_after:
			_delete_upload(file_doc)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=20, seconds=3600, key="scan_me_cert_cancel")
def cancel_cert_upload(file_url: str) -> dict:
	"""Delete a temporary PKCS#12 upload — called by the dialog when the admin
	closes without installing, so the .pfx never lingers under private files."""
	frappe.only_for("System Manager")
	try:
		file_doc, _abs_path = _resolve_uploaded_file(file_url)
	except frappe.ValidationError:
		# Already gone, or never existed — treat as no-op.
		return {"deleted": False}
	_delete_upload(file_doc)
	return {"deleted": True}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=5, seconds=3600, key="scan_me_cert_regen")
def regenerate_signing_cert():
	"""Wipe the PAdES PKCS#12 + its password so the next PDF signing call
	regenerates a fresh self-signed cert using the current display-name
	settings. System Manager only."""
	frappe.only_for("System Manager")

	from frappe.installer import update_site_config

	from scan_me.utils.pades import PFX_PASSWORD_KEY

	path = _safe_pfx_path()
	scan_dir = os.path.dirname(path)
	removed = False
	if os.path.exists(path):
		ts = int(time.time())
		backup_path = os.path.join(scan_dir, f"signing.pfx.{ts}.bak")
		try:
			shutil.copy2(path, backup_path)
			os.chmod(backup_path, 0o600)
		except OSError:
			pass
		os.remove(path)
		removed = True
		_rotate_backups(scan_dir)

	password_cleared = False
	if frappe.conf.get(PFX_PASSWORD_KEY):
		update_site_config(PFX_PASSWORD_KEY, None)
		frappe.conf.pop(PFX_PASSWORD_KEY, None)
		password_cleared = True

	_audit("regenerate_signing_cert", fingerprint_hex=None)
	return {"pfx_removed": removed, "password_cleared": password_cleared}
