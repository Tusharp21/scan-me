# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
import frappe
import hashlib
import uuid

@frappe.whitelist()
def generate_verified_qr(doctype, docname):
    """Generate Verified QR and create entry in Verified QR Master (if not exists)."""
    
    settings = frappe.get_single("Scan Me Settings")
    allowed_doctypes = [d.ref_doctype for d in settings.get("ref_doctype_info") if d.enable]

    if doctype not in allowed_doctypes:
        frappe.throw("This doctype is not allowed for Verified QR generation. Please configure it in 'Scan Me Settings'.")

    existing_qr = frappe.db.get_value(
        "Verified QR",
        {"ref_doctype": doctype, "ref_docname": docname},
        ["name", "uuid", "hash_value"],
        as_dict=True
    )

    if existing_qr:
        return {
            "message": "Verified QR already exists for this document.",
            "hash": existing_qr.hash_value,
            "uuid": existing_qr.uuid,
            "existing": True
        }

    doc = frappe.get_doc(doctype, docname)
    key_data = f"{doctype}|{docname}|{doc.modified}|{doc.owner}|{doc.creation}"
    hash_value = hashlib.sha256(key_data.encode()).hexdigest()
    unique_id = str(uuid.uuid4())

    qr_master = frappe.get_doc({
        "doctype": "Verified QR",
        "ref_doctype": doctype,
        "ref_docname": docname,
        "uuid": unique_id,
        "hash_value": hash_value,
        "created_on": frappe.utils.now(),
        "verified_count": 0,
        "last_verified_on": None,
    })
    qr_master.insert(ignore_permissions=True)

    return {
        "message": "Verified QR created successfully!",
        "hash": hash_value,
        "uuid": unique_id,
        "existing": False
    }
