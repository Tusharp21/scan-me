// Copyright (c) 2025, Tushar Patel and contributors
// For license information, please see license.txt

// Surfaces configuration combinations that partially neutralise each other,
// renders the active signing-certificate status panel, and wires the two
// in-form action buttons (Upload Production Certificate, Regenerate
// Self-Signed). All privileged operations route through scan_me.api.admin
// which enforces System Manager + rate-limit + audit-log server-side.

frappe.ui.form.on("Scan Me Settings", {
	refresh(frm) {
		apply_config_warnings(frm);
		render_cert_status(frm);
	},

	lock_verified_qr(frm) {
		apply_config_warnings(frm);
	},

	enable_content_hash(frm) {
		apply_config_warnings(frm);
	},

	enable_pades_signing(frm) {
		apply_config_warnings(frm);
	},

	signature_type(frm) {
		apply_config_warnings(frm);
	},

	upload_cert_btn(frm) {
		open_upload_dialog(frm);
	},

	regenerate_cert_btn(frm) {
		confirm_and_regenerate(frm);
	},
});

function apply_config_warnings(frm) {
	if (!frm.dashboard) return;
	frm.dashboard.clear_headline();

	const warnings = [];

	if (frm.doc.lock_verified_qr && !frm.doc.enable_content_hash) {
		warnings.push(
			__(
				"Signature records are locked but content hashing is off — tampered documents won't be flagged on the verify page. Enable 'Detect Tampering with Content Hash' for full protection."
			)
		);
	}

	const sig_type = frm.doc.signature_type || "";
	const wants_pades = sig_type === "Cryptographic (PAdES)" || sig_type === "Both";
	if (wants_pades && !frm.doc.enable_pades_signing) {
		warnings.push(
			__(
				"Signature Type is set to '{0}' but 'Apply Real Digital Signature to PDFs (PAdES)' is off — only the visual stamp will be applied. Enable PAdES above to get Adobe's signature panel.",
				[sig_type]
			)
		);
	}

	if (warnings.length) {
		frm.dashboard.set_headline(warnings.map((w) => `• ${w}`).join("<br>"), "orange");
	}
}

function confirm_and_regenerate(frm) {
	frappe.confirm(
		__(
			"This deletes the current self-signed PAdES certificate and its password. The next PDF signed with PAdES will auto-generate a fresh self-signed certificate using the display name configured below.<br><br><b>Previously signed PDFs remain valid</b> — their signature is embedded in the file. Only newly generated PDFs use the new certificate.<br><br><b>Note:</b> this is for self-signed certs only. If you have a CA-issued production certificate installed, use Upload Production Certificate instead to replace it.<br><br>Continue?"
		),
		() => {
			frappe.call({
				method: "scan_me.api.admin.regenerate_signing_cert",
				freeze: true,
				freeze_message: __("Regenerating certificate…"),
				callback: (r) => {
					if (r && r.message) {
						frappe.show_alert({
							message: __(
								"Self-signed certificate cleared. New cert will be generated on next PDF sign."
							),
							indicator: "green",
						});
						render_cert_status(frm);
					}
				},
			});
		}
	);
}

// ───────────────────────────── status panel ─────────────────────────────

function render_cert_status(frm) {
	const $wrap = frm.fields_dict.cert_status_html && frm.fields_dict.cert_status_html.$wrapper;
	if (!$wrap) return;
	$wrap.html(skeleton_html());

	frappe.call({
		method: "scan_me.api.admin.cert_status_info",
		callback: (r) => {
			const data = (r && r.message) || {};
			$wrap.html(cert_status_html(data));
		},
		error: (err) => {
			$wrap.html(
				`<div class="sm-cert-card sm-cert-error">${__(
					"Could not read certificate status"
				)}: ${frappe.utils.escape_html((err && err.message) || String(err))}</div>`
			);
		},
	});
}

function skeleton_html() {
	return `<div class="sm-cert-card sm-cert-skeleton">${__("Loading certificate status…")}</div>`;
}

function cert_status_html(d) {
	if (!d || !d.installed) {
		return wrap_card(
			"warn",
			"⚪",
			__("No signing certificate installed"),
			__(
				"A fresh self-signed certificate will be auto-generated on the first PAdES-signed PDF."
			)
		);
	}

	if (d.installed && !d.readable) {
		return wrap_card(
			"err",
			"🔴",
			__("Certificate state error"),
			__("The PKCS#12 file is present but cannot be read") +
				": " +
				frappe.utils.escape_html(d.error || "")
		);
	}

	const subject_short = pick_cn(d.subject) || d.subject;
	const issuer_short = pick_cn(d.issuer) || d.issuer;

	let indicator;
	let level;
	let headline;
	let body;

	if (d.is_self_signed) {
		indicator = "🔴";
		level = "warn";
		headline = __("Self-signed — recipients see yellow ⚠ in Adobe");
		body = __(
			"This works for internal use only. For external recipients to see a green ✓, install a CA-issued document-signing certificate via Upload Production Certificate."
		);
	} else if (d.is_expired) {
		indicator = "🔴";
		level = "err";
		headline = __("Certificate is expired");
		body = __("PDFs signed with this cert will fail validation. Renew and re-upload.");
	} else if (d.days_to_expiry < 30) {
		indicator = "🟡";
		level = "warn";
		headline = __("Certificate expires in {0} days", [d.days_to_expiry]);
		body = __(
			"Plan a renewal soon — once expired, all new signatures will be flagged invalid."
		);
	} else {
		indicator = "🟢";
		level = "ok";
		headline = __("CA-issued certificate active");
		body = d.ca_hint
			? __(
					"Issuer recognised: {0}. If this CA is on Adobe's AATL (most major CAs are), recipients see green ✓ without any setup.",
					[d.ca_hint]
			  )
			: __("Recipients see green ✓ in Adobe Reader if this issuer is on Adobe's AATL list.");
	}

	const warnings = [];
	if (!d.digital_signature) {
		warnings.push(
			__(
				"Key Usage does not include digital_signature — some strict verifiers may reject signatures."
			)
		);
	}
	if (d.not_yet_valid) {
		warnings.push(__("Certificate is not yet valid (not_before is in the future)."));
	}

	const fingerprint_short =
		(d.fingerprint_sha256 || "")
			.match(/.{1,2}/g)
			?.slice(0, 8)
			.join(":") || "";
	const not_before = format_date(d.not_before);
	const not_after = format_date(d.not_after);
	const days_label =
		d.days_to_expiry < 0
			? __("expired {0} days ago", [-d.days_to_expiry])
			: __("expires in {0} days", [d.days_to_expiry]);

	const detail_rows = [
		row(__("Signer (Subject)"), frappe.utils.escape_html(subject_short)),
		row(__("Issued by"), frappe.utils.escape_html(issuer_short)),
		row(__("Valid"), `${not_before} → ${not_after} (${days_label})`),
		row(__("SHA-256 fingerprint"), `<code>${fingerprint_short}…</code>`),
	];

	return `
		<div class="sm-cert-card sm-cert-${level}">
			<div class="sm-cert-headline">
				<span class="sm-cert-indicator">${indicator}</span>
				<span class="sm-cert-title">${frappe.utils.escape_html(headline)}</span>
			</div>
			<div class="sm-cert-body">${frappe.utils.escape_html(body)}</div>
			${
				warnings.length
					? `<div class="sm-cert-warnings">${warnings
							.map((w) => `<div>⚠ ${frappe.utils.escape_html(w)}</div>`)
							.join("")}</div>`
					: ""
			}
			<table class="sm-cert-details">${detail_rows.join("")}</table>
		</div>
		${cert_status_styles()}
	`;
}

function row(label, valueHtml) {
	return `<tr><td class="sm-cert-label">${frappe.utils.escape_html(
		label
	)}</td><td class="sm-cert-value">${valueHtml}</td></tr>`;
}

function wrap_card(level, indicator, headline, body) {
	return `
		<div class="sm-cert-card sm-cert-${level}">
			<div class="sm-cert-headline">
				<span class="sm-cert-indicator">${indicator}</span>
				<span class="sm-cert-title">${frappe.utils.escape_html(headline)}</span>
			</div>
			<div class="sm-cert-body">${frappe.utils.escape_html(body)}</div>
		</div>
		${cert_status_styles()}
	`;
}

function pick_cn(rfc4514) {
	if (!rfc4514) return "";
	const m = rfc4514.match(/(?:^|,)\s*CN=([^,]+)/i);
	return m ? m[1] : "";
}

function format_date(iso) {
	if (!iso) return "—";
	try {
		const d = new Date(iso);
		return d.toLocaleDateString(undefined, {
			year: "numeric",
			month: "short",
			day: "numeric",
		});
	} catch (e) {
		return iso;
	}
}

function cert_status_styles() {
	if (window.__sm_cert_styles_injected) return "";
	window.__sm_cert_styles_injected = true;
	return `<style>
		.sm-cert-card { border:1px solid var(--border-color,#e5e7eb); border-radius:8px; padding:14px 16px; background:var(--card-bg,#fff); }
		.sm-cert-card.sm-cert-ok { border-color:#bbf7d0; background:#f0fdf4; }
		.sm-cert-card.sm-cert-warn { border-color:#fde68a; background:#fffbeb; }
		.sm-cert-card.sm-cert-err { border-color:#fecaca; background:#fef2f2; }
		.sm-cert-card.sm-cert-skeleton { color:var(--text-muted,#6b7280); font-size:12px; }
		.sm-cert-headline { display:flex; align-items:center; gap:8px; font-weight:600; margin-bottom:6px; }
		.sm-cert-indicator { font-size:18px; }
		.sm-cert-title { font-size:14px; }
		.sm-cert-body { font-size:13px; color:var(--text-color,#1f2937); margin-bottom:10px; }
		.sm-cert-warnings { font-size:12px; color:#92400e; margin-bottom:10px; }
		.sm-cert-warnings > div { margin-top:2px; }
		.sm-cert-details { font-size:12px; width:100%; border-collapse:collapse; margin-top:8px; }
		.sm-cert-details td { padding:4px 8px; border-top:1px solid rgba(0,0,0,0.04); vertical-align:top; }
		.sm-cert-details td.sm-cert-label { color:var(--text-muted,#6b7280); width:38%; white-space:nowrap; }
		.sm-cert-details td.sm-cert-value { word-break:break-word; font-family:inherit; }
		.sm-cert-details code { font-size:11px; }
	</style>`;
}

// ───────────────────────────── upload dialog ─────────────────────────────

function open_upload_dialog(frm) {
	let installed = false;
	let last_validated_url = null;

	const d = new frappe.ui.Dialog({
		title: __("Upload Production Certificate"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "intro",
				options: `<div style="font-size:12px;color:var(--text-muted,#6b7280);margin-bottom:8px">${__(
					"Upload a CA-issued PKCS#12 (.pfx / .p12) bundle from a document-signing CA (Sectigo, GlobalSign, eMudhra, DigiCert, etc.). Maximum file size: 100 KB. The uploaded file is stored as a private attachment and auto-deleted after install."
				)}</div>`,
			},
			{
				fieldtype: "Attach",
				fieldname: "pfx_file",
				label: __("Certificate File (.pfx / .p12)"),
				reqd: 1,
				// is_private + size + extension restrictions enforced by Frappe's
				// upload dialog client-side, then re-checked on the server.
				options: {
					restrictions: {
						allowed_file_types: [".pfx", ".p12"],
						max_file_size: 100 * 1024,
					},
					is_private: 1,
				},
			},
			{
				fieldtype: "Password",
				fieldname: "pfx_password",
				label: __("Password"),
				reqd: 1,
			},
			{ fieldtype: "Section Break" },
			{
				fieldtype: "HTML",
				fieldname: "preview",
				options: `<div style="font-size:12px;color:var(--text-muted,#6b7280)">${__(
					"Click Validate to preview the certificate before installing."
				)}</div>`,
			},
		],
		primary_action_label: __("Validate"),
		primary_action: () => validate_then_show_install(d),
	});

	// Carry the form ref on the dialog so deep callbacks (install_cert) can
	// refresh the cert status without reaching for the deprecated cur_frm.
	d._frm = frm;

	// Track the most recent attached URL so we can call cancel_cert_upload on
	// dialog close if the admin never clicked Install. Also covers the case
	// where they attach file A, replace it with file B — A's File doc would
	// otherwise stick around.
	d.fields_dict.pfx_file.df.change = () => {
		const new_url = d.get_value("pfx_file");
		if (last_validated_url && last_validated_url !== new_url) {
			cleanup_upload(last_validated_url);
		}
		last_validated_url = new_url || null;
		// Any swap invalidates the preview.
		d.fields_dict.preview.$wrapper.html(
			`<div style="font-size:12px;color:var(--text-muted,#6b7280)">${__(
				"Click Validate to preview the certificate before installing."
			)}</div>`
		);
		d.set_primary_action(__("Validate"), () => validate_then_show_install(d));
	};

	d._mark_installed = () => {
		installed = true;
	};

	d.$wrapper.on("hidden.bs.modal", () => {
		try {
			d.set_value("pfx_password", "");
		} catch (e) {
			/* dialog already torn down */
		}
		// If user closed without installing, the temp upload must be cleaned up.
		if (!installed) {
			const url = d.get_value && d.get_value("pfx_file");
			if (url) cleanup_upload(url);
		}
	});

	d.show();
}

function cleanup_upload(file_url) {
	if (!file_url) return;
	frappe.call({
		method: "scan_me.api.admin.cancel_cert_upload",
		args: { file_url },
		// Silent on error — the cleanup is belt-and-suspenders; server-side
		// orphans can still be removed via File List in the desk if needed.
	});
}

function validate_then_show_install(d) {
	const file_url = d.get_value("pfx_file");
	const password = d.get_value("pfx_password");

	if (!file_url || !password) {
		frappe.msgprint({
			title: __("Missing input"),
			message: __("Both certificate file and password are required."),
			indicator: "orange",
		});
		return;
	}

	d.disable_primary_action();
	d.fields_dict.preview.$wrapper.html(
		`<div style="font-size:12px;color:var(--text-muted,#6b7280)">${__("Validating…")}</div>`
	);

	frappe.call({
		method: "scan_me.api.admin.validate_cert_upload",
		args: { file_url, password },
		callback: (r) => {
			const msg = (r && r.message) || {};
			if (!msg.ok) {
				render_validate_failure(d, __("Validation failed."));
				d.enable_primary_action();
				return;
			}
			render_validate_preview(d, msg, { file_url, password });
		},
		error: () => {
			render_validate_failure(d, __("Server rejected the upload — see Error Log."));
			d.enable_primary_action();
		},
	});
}

function render_validate_preview(d, msg, payload) {
	const c = msg.cert || {};
	const warnings = msg.warnings || [];
	const subject = pick_cn(c.subject) || c.subject || "—";
	const issuer = pick_cn(c.issuer) || c.issuer || "—";
	const not_before = format_date(c.not_before);
	const not_after = format_date(c.not_after);
	const fp =
		(c.fingerprint_sha256 || "")
			.match(/.{1,2}/g)
			?.slice(0, 12)
			.join(":") || "";
	const days = c.days_to_expiry;
	const days_text =
		days < 0 ? __("expired {0} days ago", [-days]) : __("expires in {0} days", [days]);

	const warning_html = warnings.length
		? `<div style="margin-top:10px;font-size:12px;color:#92400e;background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:8px">${warnings
				.map((w) => `<div>⚠ ${frappe.utils.escape_html(w)}</div>`)
				.join("")}</div>`
		: "";

	d.fields_dict.preview.$wrapper.html(`
		<div style="border:1px solid #d1d5db;border-radius:8px;padding:12px 14px;background:#f9fafb">
			<div style="font-weight:600;margin-bottom:8px">${__("Certificate Preview")}</div>
			<table style="font-size:12px;width:100%;border-collapse:collapse">
				<tr><td style="color:#6b7280;padding:3px 8px;width:35%">${__(
					"Subject"
				)}</td><td style="padding:3px 8px">${frappe.utils.escape_html(subject)}</td></tr>
				<tr><td style="color:#6b7280;padding:3px 8px">${__(
					"Issuer"
				)}</td><td style="padding:3px 8px">${frappe.utils.escape_html(issuer)}</td></tr>
				<tr><td style="color:#6b7280;padding:3px 8px">${__(
					"Valid"
				)}</td><td style="padding:3px 8px">${not_before} → ${not_after} (${days_text})</td></tr>
				<tr><td style="color:#6b7280;padding:3px 8px">${__(
					"Self-signed?"
				)}</td><td style="padding:3px 8px">${
		c.is_self_signed ? __("yes") : __("no")
	}</td></tr>
				<tr><td style="color:#6b7280;padding:3px 8px">${__(
					"digital_signature usage"
				)}</td><td style="padding:3px 8px">${c.digital_signature ? "✓" : "✗"}</td></tr>
				<tr><td style="color:#6b7280;padding:3px 8px">${__(
					"SHA-256 fingerprint"
				)}</td><td style="padding:3px 8px"><code style="font-size:11px">${fp}…</code></td></tr>
			</table>
			${warning_html}
		</div>
	`);

	d.set_primary_action(__("Install Certificate"), () =>
		install_cert(d, payload.file_url, payload.password)
	);
}

function render_validate_failure(d, fallback) {
	d.fields_dict.preview.$wrapper.html(
		`<div style="font-size:12px;color:#b91c1c">${frappe.utils.escape_html(fallback)}</div>`
	);
}

function install_cert(d, file_url, password) {
	d.disable_primary_action();
	frappe.call({
		method: "scan_me.api.admin.install_cert_upload",
		args: { file_url, password },
		freeze: true,
		freeze_message: __("Installing certificate…"),
		callback: (r) => {
			if (r && r.message && r.message.installed) {
				// Server already deleted the temp File doc; mark so the dialog's
				// hidden-handler doesn't call cancel_cert_upload again.
				if (typeof d._mark_installed === "function") d._mark_installed();
				frappe.show_alert({
					message: __(
						"Certificate installed. New PDFs will be signed with the new identity."
					),
					indicator: "green",
				});
				d.hide();
				if (d._frm) render_cert_status(d._frm);
			} else {
				d.enable_primary_action();
			}
		},
		error: () => {
			d.enable_primary_action();
		},
	});
}
