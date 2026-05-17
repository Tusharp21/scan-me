import frappe


def execute():
	"""Backfill signature_type (JSON default doesn't apply to existing Single records).
	Installs with enable_pades_signing on get 'Both' to preserve PAdES output."""
	if not frappe.db.exists("DocType", "Scan Me Settings"):
		return

	current = frappe.db.get_single_value("Scan Me Settings", "signature_type")
	if current:
		return

	pades_on = frappe.db.get_single_value("Scan Me Settings", "enable_pades_signing") in (1, "1", True)
	default = "Both" if pades_on else "Visual Block"
	frappe.db.set_single_value("Scan Me Settings", "signature_type", default)
	frappe.db.commit()
