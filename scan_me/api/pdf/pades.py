# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""PAdES wrapper around scan_me.utils.pades. Both admin toggle and per-render flag
must be on; failures swallow to unsigned bytes so signing never blocks downloads."""

import frappe

from .signature import _fetch_signature_records


def _maybe_pades_sign(pdf_bytes, opts, doctype, name):
	"""PyHanko-sign when both apply_pades (dialog) and enable_pades_signing (admin) are on."""
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
