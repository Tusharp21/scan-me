# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ScanMeSettings(Document):
	def validate(self):
		# Per-row checks here: Frappe doesn't call child validate() on parent save.
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
	"""Allowlist filtered by caller's write perm — prevents low-role enumeration of privileged targets."""
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
	"""Form-JS payload: allowlist + button visibility; one call avoids 2 round trips per refresh."""
	settings = frappe.get_single("Scan Me Settings")
	# Default on for older installs missing the field.
	show = settings.get("enable_advanced_print_button") in (None, 1, "1", True)
	return {
		"allowed_doctypes": _user_allowed_doctypes(),
		"show_advanced_print_button": 1 if show else 0,
	}


@frappe.whitelist(allow_guest=False)
def get_print_defaults(doctype):
	"""Default Print Format + Letter Head for a doctype; gated by print perm to block enumeration."""
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
	"""UI toggle flags for the print dialog. Pure UI flags — no per-caller filtering needed."""
	s = frappe.get_single("Scan Me Settings")
	# Default on for any flag missing from older installs.
	return {
		"show_copies": 1 if s.get("show_copies_section") in (None, 1, "1", True) else 0,
		"show_header_footer": 1 if s.get("show_header_footer_section") in (None, 1, "1", True) else 0,
		"show_qr": 1 if s.get("show_qr_section") in (None, 1, "1", True) else 0,
		"show_signature": 1 if s.get("show_signature_section") in (None, 1, "1", True) else 0,
		"show_live_preview": 1 if s.get("show_live_preview") in (None, 1, "1", True) else 0,
		"signature_type": s.get("signature_type") or "Visual Block",
		"watermark_mode": s.get("watermark_mode") or "Disabled",
	}
