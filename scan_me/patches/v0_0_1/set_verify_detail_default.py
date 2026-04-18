import frappe


def execute():
	"""Backfill public_verify_detail = 'Standard' for existing installs.

	The JSON default applies to new inserts only; the Single record pre-dates
	the field addition and needs the explicit write.
	"""
	if not frappe.db.exists("DocType", "Scan Me Settings"):
		return
	current = frappe.db.get_single_value("Scan Me Settings", "public_verify_detail")
	if not current:
		frappe.db.set_single_value("Scan Me Settings", "public_verify_detail", "Standard")
		frappe.db.commit()
