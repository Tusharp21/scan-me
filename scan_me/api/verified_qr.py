import frappe

@frappe.whitelist(allow_guest=True)
def verify_qr(uuid):
    """Verify QR UUID or hash and return result"""
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
        return {"status": "invalid", "message": "No matching verified record found"}

    return {
        "status": "valid",
        "ref_doctype": qr.ref_doctype,
        "ref_docname": qr.ref_docname,
        "hash": qr.hash_value,
        "created_on": qr.creation,
    }
