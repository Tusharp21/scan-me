"""PAdES PDF signing via PyHanko. Auto-creates a self-signed PFX on first use;
swap signing.pfx + scan_me_signing_password in site_config to use a CA cert."""

import io
import os
import secrets
from datetime import datetime, timedelta, timezone

import frappe

PFX_RELATIVE = os.path.join("private", "files", "scan_me", "signing.pfx")
PFX_PASSWORD_KEY = "scan_me_signing_password"


def _pfx_path() -> str:
	return os.path.join(frappe.get_site_path(), PFX_RELATIVE)


def _get_or_create_password() -> str:
	password = frappe.conf.get(PFX_PASSWORD_KEY)
	if password:
		return password
	from frappe.installer import update_site_config

	password = secrets.token_urlsafe(32)
	update_site_config(PFX_PASSWORD_KEY, password)
	frappe.conf[PFX_PASSWORD_KEY] = password
	return password


def _company_name() -> str:
	"""Cert CN/O: default_company from Global Defaults, else site name."""
	try:
		default_company = frappe.db.get_single_value("Global Defaults", "default_company")
		if default_company:
			return default_company
	except Exception:
		pass
	return frappe.local.site or "Scan Me"


def _generate_self_signed_pfx(password: str) -> None:
	"""Write a fresh self-signed PKCS#12 bundle to the PFX path."""
	from cryptography import x509
	from cryptography.hazmat.primitives import hashes, serialization
	from cryptography.hazmat.primitives.asymmetric import rsa
	from cryptography.hazmat.primitives.serialization import pkcs12
	from cryptography.x509.oid import NameOID

	org = _company_name()

	private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
	subject = issuer = x509.Name(
		[
			x509.NameAttribute(NameOID.COMMON_NAME, f"{org} — Scan Me Signing"),
			x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
			x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Scan Me"),
		]
	)
	now = datetime.now(timezone.utc)
	cert = (
		x509.CertificateBuilder()
		.subject_name(subject)
		.issuer_name(issuer)
		.public_key(private_key.public_key())
		.serial_number(x509.random_serial_number())
		.not_valid_before(now - timedelta(minutes=5))
		.not_valid_after(now + timedelta(days=365 * 5))
		.add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
		.add_extension(
			x509.KeyUsage(
				digital_signature=True,
				content_commitment=True,
				key_encipherment=False,
				data_encipherment=False,
				key_agreement=False,
				key_cert_sign=False,
				crl_sign=False,
				encipher_only=False,
				decipher_only=False,
			),
			critical=True,
		)
		.add_extension(
			x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.EMAIL_PROTECTION]),
			critical=False,
		)
		.sign(private_key=private_key, algorithm=hashes.SHA256())
	)

	pfx_bytes = pkcs12.serialize_key_and_certificates(
		name=org.encode("utf-8"),
		key=private_key,
		cert=cert,
		cas=None,
		encryption_algorithm=serialization.BestAvailableEncryption(password.encode("utf-8")),
	)

	path = _pfx_path()
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "wb") as fh:  # nosemgrep: frappe-security-file-traversal
		fh.write(pfx_bytes)
	os.chmod(path, 0o600)


def ensure_signing_cert() -> tuple[str, str]:
	"""Ensure PKCS#12 bundle exists; returns (path, password)."""
	password = _get_or_create_password()
	path = _pfx_path()
	if not os.path.exists(path):
		_generate_self_signed_pfx(password)
	return path, password


def sign_pdf(
	pdf_bytes: bytes,
	doctype: str,
	name: str,
	signers: list[dict] | None = None,
) -> bytes:
	"""Apply a PAdES signature and return the signed bytes."""
	from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
	from pyhanko.sign import PdfSignatureMetadata
	from pyhanko.sign import signers as pyhanko_signers
	from pyhanko.sign.fields import SigFieldSpec, SigSeedSubFilter, append_signature_field
	from pyhanko.stamp import TextStampStyle

	pfx_path, password = ensure_signing_cert()
	signer = pyhanko_signers.SimpleSigner.load_pkcs12(
		pfx_file=pfx_path,
		passphrase=password.encode("utf-8"),
	)

	signer_names = []
	if signers:
		for s in signers:
			if s.get("full_name"):
				signer_names.append(s["full_name"])
	signer_summary = ", ".join(signer_names) if signer_names else "Scan Me"

	reason = f"Scan Me Verified — {doctype}: {name}"
	if signer_names:
		reason = f"Signed by {signer_summary} ({doctype}: {name})"

	from pypdf import PdfReader

	page_count = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
	last_page_index = max(0, page_count - 1)

	in_buf = io.BytesIO(pdf_bytes)
	writer = IncrementalPdfFileWriter(in_buf)

	# Stamp box (PDF points, 1/72"): bottom-right of last page, 180x60 on A4 595x842.
	stamp_box = (380, 40, 560, 100)
	field_name = "ScanMeSignature"
	append_signature_field(
		writer,
		SigFieldSpec(
			sig_field_name=field_name,
			on_page=last_page_index,
			box=stamp_box,
		),
	)

	stamp_style = TextStampStyle(
		stamp_text=("Digitally signed by %(signer)s\n" "Date: %(ts)s\n" "Doc: %(doc)s"),
		background=None,
	)

	meta = PdfSignatureMetadata(
		field_name=field_name,
		reason=reason,
		location=frappe.utils.get_url() or "",
		name=signer_summary,
		subfilter=SigSeedSubFilter.PADES,
	)

	pdf_signer = pyhanko_signers.PdfSigner(
		signature_meta=meta,
		signer=signer,
		stamp_style=stamp_style,
	)

	out_buf = io.BytesIO()
	pdf_signer.sign_pdf(
		writer,
		output=out_buf,
		appearance_text_params={
			"signer": signer_summary,
			"ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
			"doc": f"{doctype}: {name}",
		},
	)
	return out_buf.getvalue()
