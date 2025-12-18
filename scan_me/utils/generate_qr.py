# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
import uuid

import frappe


@frappe.whitelist()
def generate_verified_qr(doctype, docname, signature_data=None):
	"""Generate a Verified QR for a document."""

	settings = frappe.get_single("Scan Me Settings")
	allowed_doctypes = [d.ref_doctype for d in settings.get("ref_doctype_info") if d.enable]
	if doctype not in allowed_doctypes:
		frappe.throw(
			"This doctype is not allowed for Verified QR generation. Please configure it in 'Scan Me Settings'."
		)

	signed_by = frappe.session.user
	signed_on = frappe.utils.now()

	if frappe.session.user == "administrator":
		frappe.throw("Administrator cannot sign documents.")

	criteria = {"ref_doctype": doctype, "ref_docname": docname}
	if signature_data:
		criteria["signed_by"] = signed_by

	existing_qr = frappe.db.get_value("Verified QR", criteria, ["name", "unique_id"], as_dict=True)
	if existing_qr:
		return {
			"message": "Verified QR already exists for this document.",
			"existing": True,
		}

	unique_id = str(uuid.uuid4())
	qr_master = frappe.get_doc(
		{
			"doctype": "Verified QR",
			"ref_doctype": doctype,
			"ref_docname": docname,
			"unique_id": unique_id,
			"created_on": frappe.utils.now(),
			"verified_count": 0,
			"last_verified_on": None,
			**({"signature": signature_data} if signature_data else {}),
			**({"signed_by": signed_by} if signed_by else {}),
			**({"signed_on": signed_on} if signed_on else {}),
		}
	)
	qr_master.insert(ignore_permissions=True)

	return {
		"message": "Verified QR created successfully!",
		"existing": False,
	}
