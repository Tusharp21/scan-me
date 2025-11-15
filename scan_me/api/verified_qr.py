import frappe
from frappe.rate_limiter import rate_limit

@frappe.whitelist(allow_guest=True)
@rate_limit(key="verify_qr",limit=10, seconds=60)
def verify_qr(uuid=None):

    if not uuid:
        uuid = frappe.form_dict.get("uuid")

    if not uuid:
        return {"status": "error", "message": "No QR data provided"}

    qr = frappe.db.get_value(
        "Verified QR",
        {"uuid": uuid},
        ["ref_doctype", "ref_docname", "hash_value", "creation"],
        as_dict=True,
    )

    if not qr:
        qr = frappe.db.get_value(
            "Verified QR",
            {"hash_value": uuid},
            ["ref_doctype", "ref_docname", "hash_value", "creation"],
            as_dict=True,
        )

    if not qr:
        return {
            "status": "invalid",
            "title": "Unable to Validate",
            "message": (
                "The provided QR code is not associated with any approved record.<br>"
                "Kindly recheck the document and attempt verification again."
            )
        }

    return {
        "status": "valid",
        "title": "Document Authenticated",
        "message": (
            "You may continue with the next required step."
        ),
        "ref_doctype": qr.ref_doctype,
        "ref_docname": qr.ref_docname,
        "hash": qr.hash_value,
        "created_on": qr.creation,
    }
