import frappe


def execute():
	"""Backfill dialog toggles to on; new Check fields get ALTER TABLE default 0,
	JSON default only applies to new inserts so existing Single records need this."""
	if not frappe.db.exists("DocType", "Scan Me Settings"):
		return

	fields = [
		"show_copies_section",
		"show_header_footer_section",
		"show_qr_section",
		"show_signature_section",
		"show_live_preview",
	]
	for f in fields:
		if frappe.db.get_single_value("Scan Me Settings", f) in (None, 0, "0"):
			frappe.db.set_single_value("Scan Me Settings", f, 1)
	frappe.db.commit()
