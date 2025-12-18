/* global QRCode */

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
			allowed_doctypes.forEach((dt) => {
				frappe.ui.form.on(dt, {
					refresh(frm) {
						if (!frm || frm.is_new() || !frm.doc) return;

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

function add_generate_qr_button(frm) {
	if (!frm || !frm.doctype) return;

	frappe.call({
		method: "scan_me.scan_me.doctype.verified_qr.verified_qr.check_button_required",
		args: { doctype: frm.doctype, docname: frm.doc.name },
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

function generate_verified_qr(frm) {
	frappe.call({
		method: "scan_me.scan_me.doctype.verified_qr.verified_qr.check_signature_required",
		args: { doctype: frm.doctype },
		callback(r) {
			if (!r.message) return;

			const is_signature_required = r.message;
			if (is_signature_required) {
				if (frappe.session.user == "Administrator") {
					frappe.throw("Administrator cannot sign documents.");
				}

				signature_required(frm);
			} else {
				frappe.call({
					method: "scan_me.utils.generate_qr.generate_verified_qr",
					args: {
						doctype: frm.doctype,
						docname: frm.doc.name,
					},
					freeze: true,
					freeze_message: __("Generating Verified QR..."),
					callback(res) {
						if (res.message?.existing) {
							frappe.msgprint({
								message: __(
									res.message.message || "Verified QR Created Successfully."
								),
								title: __("Info"),
								indicator: "green",
							});
							frm.reload_doc();
						}
					},
				});
			}
		},
	});
}

function signature_required(frm) {
	let d = new frappe.ui.Dialog({
		title: "Signature Required",
		fields: [
			{
				label: "Signed By",
				fieldname: "signed_by",
				fieldtype: "Link",
				options: "User",
				default: frappe.session.user,
				readonly: 1,
			},
			{
				fieldtype: "column_break",
			},
			{
				label: "Signed On",
				fieldname: "signed_on",
				fieldtype: "Date",
				readonly: 1,
				default: frappe.datetime.get_today(),
			},
			{
				fieldtype: "section_break",
			},
			{
				label: "Signature",
				fieldname: "signature",
				fieldtype: "Signature",
			},
		],
		size: "large",
		primary_action_label: "Sign QR",
		primary_action(values) {
			console.log(values);

			frappe.call({
				method: "scan_me.utils.generate_qr.generate_verified_qr",
				args: {
					doctype: frm.doctype,
					docname: frm.doc.name,
					signature_data: values.signature,
				},
				freeze: true,
				freeze_message: __("Generating Verified QR..."),
				callback(res) {
					let response = res.message;
					frappe.msgprint({
						message: __(response.message),
						title: __("Info"),
						indicator: "green",
					});
					frm.reload_doc();
					d.hide();
				},
			});
		},
	});

	d.show();
}

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
