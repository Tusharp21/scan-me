import frappe


def execute():
	"""Backfill Scan Me Settings → signature_type = 'Visual Block' on existing installs.

	New Select fields added to an existing Single record don't pick up the JSON
	default automatically — the column lands empty and needs an explicit write.
	Existing installs with ``enable_pades_signing`` already on get "Both" so the
	print page's single "Apply Signature" checkbox keeps producing PAdES output.
	"""
	if not frappe.db.exists("DocType", "Scan Me Settings"):
		return

	current = frappe.db.get_single_value("Scan Me Settings", "signature_type")
	if current:
		return

	pades_on = frappe.db.get_single_value("Scan Me Settings", "enable_pades_signing") in (1, "1", True)
	default = "Both" if pades_on else "Visual Block"
	frappe.db.set_single_value("Scan Me Settings", "signature_type", default)
	frappe.db.commit()
