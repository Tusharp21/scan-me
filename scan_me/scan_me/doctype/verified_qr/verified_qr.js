// Copyright (c) 2025, Tushar Patel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Verified QR", {
	refresh(frm) {
        if (!frm.doc) return;

        frm.fields.forEach(f => {
            const fieldname = f.df.fieldname;
            const desc = (f.df.description || "").toLowerCase();
            // Check if description mentions 'qr'
            if (desc.includes("qr")) {
                const value = frm.doc[fieldname];
                add_qr_to_description(frm, fieldname, value);
            }
        });
	},
});
