# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ScanMeSettings(Document):
	def validate(self):
		# Frappe doesn't call a child row's controller validate() during the
		# parent's save flow, so the per-row checks have to live here on the
		# parent. We block two doctype kinds that would break signing later:
		# Singles have no per-record name to attach a Verified QR to, and
		# child tables can't be signed standalone (Verified QR has no
		# parent-row coordinates). Letting either into the allowlist would
		# trip a traceback inside generate_verified_qr at sign time; catching
		# it at config save gives the admin a clear message instead.
		for row in self.get("ref_doctype_info") or []:
			if not row.ref_doctype:
				continue
			meta = frappe.get_meta(row.ref_doctype)
			if getattr(meta, "issingle", 0):
				frappe.throw(
					frappe._(
						"'{0}' is a Single doctype and can't be signed — pick a doctype with individual records."
					).format(row.ref_doctype)
				)
			if getattr(meta, "istable", 0):
				frappe.throw(
					frappe._(
						"'{0}' is a child table and can't be signed on its own — pick the parent doctype instead."
					).format(row.ref_doctype)
				)


def _user_allowed_doctypes():
	"""Return the admin-configured allowlist filtered to what the caller can sign.

	The raw allowlist in Scan Me Settings is admin-only data — exposing it in
	full to every authenticated user lets a low-role account enumerate which
	doctypes are privileged targets. We filter to doctypes where the caller
	has role-level ``write`` permission (signing is a write action), so a user
	who couldn't generate a QR on a given doctype never sees it listed.
	"""
	settings = frappe.get_single("Scan Me Settings")
	return [
		d.ref_doctype
		for d in (settings.get("ref_doctype_info") or [])
		if d.enable and frappe.has_permission(d.ref_doctype, "write")
	]


@frappe.whitelist(allow_guest=False)
def get_allowed_doctypes():
	"""Get the subset of allowlisted doctypes the caller can actually sign."""
	return _user_allowed_doctypes()


@frappe.whitelist(allow_guest=False)
def get_form_integration():
	"""Single payload for the form-level JS (allowlist + button visibility flag).

	Called from public/js/hardcopy_button.js on desk load. Combining into one
	call avoids two round trips per form refresh. ``allowed_doctypes`` is
	filtered by the caller's write permission so the Advanced Print button
	doesn't get registered on forms they couldn't sign anyway.
	"""
	settings = frappe.get_single("Scan Me Settings")
	# Default to on for older installs missing the field.
	show = settings.get("enable_advanced_print_button") in (None, 1, "1", True)
	return {
		"allowed_doctypes": _user_allowed_doctypes(),
		"show_advanced_print_button": 1 if show else 0,
	}


@frappe.whitelist(allow_guest=False)
def get_print_defaults(doctype):
	"""Return the sensible default Print Format and Letter Head for a doctype.

	Default print format is stored on the DocType record itself
	(``DocType.default_print_format``), not as a flag on Print Format rows.
	Default letter head comes from the Letter Head with ``is_default=1``.
	Requires role-level print permission on ``doctype`` so this endpoint
	can't be used by a low-role user as an oracle for per-doctype print
	configuration.
	"""
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(
			frappe._("DocType {0} does not exist.").format(doctype),
			frappe.DoesNotExistError,
		)
	if not frappe.has_permission(doctype, "print"):
		frappe.throw(
			frappe._("No permission to print '{0}'.").format(doctype),
			frappe.PermissionError,
		)
	pf = frappe.db.get_value("DocType", doctype, "default_print_format") or "Standard"
	lh = (
		frappe.db.get_value(
			"Letter Head",
			{"is_default": 1, "disabled": 0},
			"name",
		)
		or ""
	)
	return {"print_format": pf, "letter_head": lh}


@frappe.whitelist(allow_guest=False)
def get_dialog_settings():
	"""Flags that control which sections render in the Chrome PDF print dialog.

	Authenticated-only (whitelist without ``allow_guest``). The returned flags
	are pure UI toggles — no doctype-level data, no admin secrets — so
	per-caller filtering would be pointless. If a future field here starts
	returning higher-sensitivity data, gate it explicitly rather than adding
	it to this payload.
	"""
	s = frappe.get_single("Scan Me Settings")
	# Default to on for any flag missing from older installs.
	return {
		"show_copies": 1 if s.get("show_copies_section") in (None, 1, "1", True) else 0,
		"show_header_footer": 1 if s.get("show_header_footer_section") in (None, 1, "1", True) else 0,
		"show_qr": 1 if s.get("show_qr_section") in (None, 1, "1", True) else 0,
		"show_signature": 1 if s.get("show_signature_section") in (None, 1, "1", True) else 0,
		"show_live_preview": 1 if s.get("show_live_preview") in (None, 1, "1", True) else 0,
		"signature_type": s.get("signature_type") or "Visual Block",
		"watermark_mode": s.get("watermark_mode") or "Disabled",
	}
