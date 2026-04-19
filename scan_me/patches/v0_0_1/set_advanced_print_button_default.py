import frappe


def execute():
	"""Backfill Scan Me Settings → enable_advanced_print_button = 1 on existing installs."""
	if not frappe.db.exists("DocType", "Scan Me Settings"):
		return
	current = frappe.db.get_single_value("Scan Me Settings", "enable_advanced_print_button")
	if current in (None, 0, "0"):
		frappe.db.set_single_value("Scan Me Settings", "enable_advanced_print_button", 1)
		frappe.db.commit()
