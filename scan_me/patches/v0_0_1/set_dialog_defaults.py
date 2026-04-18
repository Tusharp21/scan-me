import frappe


def execute():
	"""Turn on all dialog feature toggles for existing installs.

	New Check fields added to Scan Me Settings get ALTER TABLE default 0.
	The JSON ``"default": "1"`` only applies to new inserts, so existing
	Single records keep 0 unless we backfill.
	"""
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
