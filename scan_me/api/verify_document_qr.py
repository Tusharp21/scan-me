import frappe
from frappe.rate_limiter import rate_limit


@frappe.whitelist(allow_guest=True)
@rate_limit(key="verify_qr", limit=10, seconds=60)
def verify_document_qr(uuid=None):
	if not uuid:
		uuid = frappe.form_dict.get("uuid")

	if not uuid:
		return {"status": "error", "message": "No QR data provided"}

	qr = frappe.db.get_value(
		"Verified QR",
		{"unique_id": uuid},
		["ref_doctype", "ref_docname", "creation"],
		as_dict=True,
	)

	if not qr:
		return {
			"status": "invalid",
			"title": "Unable to Validate",
			"message": (
				"The provided QR code is not associated with any approved record.<br>"
				"Kindly recheck the document and attempt verification again."
			),
		}

	return {
		"status": "valid",
		"title": "Document Authenticated",
		"message": ("You may continue with the next required step."),
		"ref_doctype": qr.ref_doctype,
		"ref_docname": qr.ref_docname,
		"unique_id": qr.unique_id,
		"created_on": qr.creation,
	}
