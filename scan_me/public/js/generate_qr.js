/**
 * Dynamically adds a "Generate Verified QR" button on allowed doctypes.
 */

frappe.after_ajax(() => {
    frappe.call({
        method: "scan_me.scan_me.doctype.scan_me_settings.scan_me_settings.get_allowed_doctypes",
        freeze: true,
        freeze_message: __("Loading Verified QR setup..."),
        callback(r) {
            const allowed_doctypes = r.message || [];

            if (!allowed_doctypes.length) {
                console.warn("[Scan Me] No doctypes configured for Verified QR button.");
                return;
            }

            // Attach form handlers dynamically
            allowed_doctypes.forEach(dt => {
                frappe.ui.form.on(dt, {
                    refresh(frm) {
                        if (!frm || frm.is_new() || !frm.doc) return;

                        // Add button only once per refresh
                        if (!frm._has_qr_button && frm.doc.docstatus <= 2) {
                            add_generate_qr_button(frm);
                            frm._has_qr_button = true;
                        }
                    },
                });
            });
        },
    });
});


/**
 * Add "Generate Verified QR" button to a given form
 */
function add_generate_qr_button(frm) {
    if (!frm || !frm.doctype) return;

    frappe.call({
        method: "scan_me.scan_me.doctype.scan_me_settings.scan_me_settings.check_button_required",
        args: { doctype: frm.doctype },
        callback(r) {
            if (!r.message) return;

            const is_allowed = r.message;
            if (!is_allowed) return;

            frm.add_custom_button(
                __("Generate Verified QR"),
                () => generate_verified_qr(frm),
                __("Actions")
            ).addClass("btn-primary");
        },
    });
}


/**
 * Trigger backend QR generation and reload document
 */
function generate_verified_qr(frm) {
    frappe.call({
        method: "scan_me.utils.generate_qr.generate_verified_qr",
        args: {
            doctype: frm.doctype,
            docname: frm.doc.name,
        },
        freeze: true,
        freeze_message: __("Generating Verified QR..."),
        callback(res) {
            if (!res.exc) {
                frappe.msgprint({
                    message: __("Verified QR created successfully!"),
                    indicator: "green"
                });
                frm.reload_doc();
            }
        },
    });
}

/** 
 * Add QR code to field description
 */
function add_qr_to_description(frm, fieldname, value) {
    const field = frm.fields_dict[fieldname];
    if (!field) return;

    const $wrapper = field.$wrapper;
    if (!$wrapper?.length) return;

    let $desc = $wrapper.find(".help");
    if (!$desc.length) {
        $desc = $('<div class="help"></div>').appendTo($wrapper);
    }

    $desc.empty();

    const $qr_div = $('<div class="qr-code-box" style="margin: 10px 0;"></div>').appendTo($desc);

    new QRCode($qr_div[0], {
        text: value || __("No Value"),
        width: 120,
        height: 120,
    });
}