import frappe


def execute():
	"""Backfill Scan Me Settings → watermark_mode = 'Disabled' on existing installs."""
	if not frappe.db.exists("DocType", "Scan Me Settings"):
		return
	if frappe.db.get_single_value("Scan Me Settings", "watermark_mode"):
		return
	frappe.db.set_single_value("Scan Me Settings", "watermark_mode", "Disabled")
	frappe.db.commit()
