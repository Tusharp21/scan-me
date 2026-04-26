// Copyright (c) 2025, Tushar Patel and contributors
// For license information, please see license.txt

// Surface configuration combinations that are technically legal but partially
// neutralise each other — e.g. asking to LOCK signature records for tamper
// protection while leaving the per-document hash OFF gives you an immutable
// audit trail but no way to tell if the underlying document was edited.
// Warnings are re-evaluated on every refresh and when the relevant fields
// change, so admins see them immediately after toggling a related flag.

frappe.ui.form.on("Scan Me Settings", {
	refresh(frm) {
		apply_config_warnings(frm);
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
});

function apply_config_warnings(frm) {
	if (!frm.dashboard) return;
	frm.dashboard.clear_headline();

	const warnings = [];

	// Locking records without a content hash: the audit trail is immutable,
	// but tamper detection on the referenced document never runs because
	// there's no hash to compare against.
	if (frm.doc.lock_verified_qr && !frm.doc.enable_content_hash) {
		warnings.push(
			__(
				"Signature records are locked but content hashing is off — tampered documents won't be flagged on the verify page. Enable 'Detect Tampering with Content Hash' for full protection."
			)
		);
	}

	// PAdES selected as the signature type (alone or alongside the visual
	// stamp) without the 'Apply Real Digital Signature' master switch: the
	// visual block still renders, but PAdES silently degrades to off.
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
		// Yellow indicator, one combined headline so the banner isn't noisy
		// when more than one misconfig is active.
		frm.dashboard.set_headline(warnings.map((w) => `• ${w}`).join("<br>"), "orange");
	}
}
