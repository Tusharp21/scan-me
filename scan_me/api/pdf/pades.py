# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""PAdES digital signing wrapper around :mod:`scan_me.utils.pades`.

Both the global toggle (``enable_pades_signing`` in Scan Me Settings) and the
per-render flag (``apply_pades`` in the dialog) must be on for signing to
happen. Failures are swallowed and the unsigned bytes returned, so a misbehaving
signer never blocks document download.
"""

import frappe

from .signature import _fetch_signature_records


def _maybe_pades_sign(pdf_bytes, opts, doctype, name):
	"""Run the merged PDF through PyHanko if the user asked for PAdES signing.

	Requires:
	  - enable_pades_signing = 1 in Scan Me Settings (admin-gated)
	  - apply_pades = 1 in the dialog (user-selected per-render)
	Silently returns the unsigned bytes if either is off. Logs and returns
	unsigned bytes on signing failure to avoid losing the document.
	"""
	if not opts.get("apply_pades"):
		return pdf_bytes

	from scan_me.utils.verification import get_signing_settings

	if not get_signing_settings()["enable_pades_signing"]:
		return pdf_bytes

	try:
		from scan_me.utils.pades import sign_pdf

		signers = _fetch_signature_records(doctype, name) or None
		return sign_pdf(pdf_bytes, doctype, name, signers=signers)
	except Exception:
		frappe.log_error("Scan Me: PAdES signing failed", frappe.get_traceback())
		return pdf_bytes
