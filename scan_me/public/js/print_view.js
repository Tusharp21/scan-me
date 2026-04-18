// Inject the "Generate PDF" button whenever a Frappe print view is visible.
// Persistent 500ms poll so SPA navigation, Frappe re-renders, and back/forward
// all recover the button without a page refresh.
(function () {
	function findPrintToolbar() {
		if (!window.location.href.includes("/print/")) return null;

		// Prefer the toolbar inside the page that actually holds the print
		// preview — otherwise we can inject into a stale action bar that's
		// still in the DOM from a previous page (list / form).
		const preview = document.querySelector(".print-preview-wrapper, .print-format-container");
		if (preview) {
			const page = preview.closest(".page") || preview.closest(".page-container");
			if (page) {
				const t = page.querySelector(".print-toolbar, .page-actions");
				if (t) return t;
			}
		}
		return document.querySelector(".print-toolbar, .page-actions");
	}

	function tryInjectButton() {
		const toolbar = findPrintToolbar();
		if (!toolbar) return;
		if (toolbar.querySelector(".chrome-pdf-btn")) return;

		const btn = document.createElement("button");
		btn.innerText = "Generate PDF";
		btn.className = "btn btn-primary btn-sm chrome-pdf-btn";
		btn.style.marginLeft = "10px";
		btn.onclick = () => openPdfDialog();
		toolbar.appendChild(btn);
	}

	function init() {
		tryInjectButton();
		setInterval(tryInjectButton, 500);

		// Router event gives a faster first injection on SPA navigation than the
		// poll alone. Retry a few times — print view renders slightly after the event.
		if (window.frappe && frappe.router && typeof frappe.router.on === "function") {
			frappe.router.on("change", () => {
				[100, 300, 600, 1000].forEach((ms) => setTimeout(tryInjectButton, ms));
			});
		}
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", init);
	} else {
		init();
	}
})();

// --- context from print URL -----------------------------------------------

function getPrintContext() {
	const parts = window.location.href.split("/print/")[1];
	if (!parts) return null;
	const tokens = parts.split("/");
	const doctype = decodeURIComponent(tokens[0]);
	const name = decodeURIComponent(tokens[1]);
	if (!doctype || !name) return null;

	let print_format = "Standard";
	const formatEl = document.querySelector(
		'.frappe-control[data-fieldname="print_format"] .control-value a,' +
			'.frappe-control[data-fieldname="print_format"] select'
	);
	if (formatEl) {
		print_format = formatEl.getAttribute("data-value") || formatEl.value || "Standard";
	}

	const lhInput = document.querySelector('.frappe-control[data-fieldname="letterhead"] input');
	const letter_head = lhInput && lhInput.value ? lhInput.value : "";

	return { doctype, name, print_format, letter_head };
}

// --- option collection + URL builder --------------------------------------

function collectOptions(dialog) {
	const v = {};
	for (const [k, field] of Object.entries(dialog.fields_dict)) {
		if (field.get_value) v[k] = field.get_value();
	}
	return {
		copy_count: parseInt(v.copy_count || "1", 10),
		copy_labels: v.copy_labels || "",
		header_mode: v.header_mode || "All pages",
		footer_mode: v.footer_mode || "All pages",
		include_qr: v.include_qr ? 1 : 0,
		qr_position: v.qr_position || "Top Right",
		qr_source: v.qr_source || "Verified QR Link",
		qr_custom_text: v.qr_custom_text || "",
		qr_force_insert: v.qr_force_insert ? 1 : 0,
		append_signature: v.append_signature ? 1 : 0,
		signature_position: v.signature_position || "End of document",
		apply_pades: v.apply_pades ? 1 : 0,
	};
}

function buildPdfUrl(ctx, options) {
	const params = new URLSearchParams({
		doctype: ctx.doctype,
		name: ctx.name,
		print_format: ctx.print_format,
		options: JSON.stringify(options),
	});
	if (ctx.letter_head) params.set("letter_head", ctx.letter_head);
	return `/api/method/scan_me.api.pdf.generate_chrome_pdf?${params.toString()}`;
}

// --- dialog with live preview ---------------------------------------------

const COPIES_FIELDS = [
	{ fieldtype: "Section Break", label: "Copies" },
	{
		fieldtype: "Select",
		fieldname: "copy_count",
		label: "Number of Copies",
		options: ["1", "2", "3"],
		default: "1",
	},
	{
		fieldtype: "Small Text",
		fieldname: "copy_labels",
		label: "Copy Labels (comma-separated)",
		default: "ORIGINAL, DUPLICATE, TRIPLICATE",
		depends_on: "eval:doc.copy_count > 1",
	},
];

const HEADER_FOOTER_FIELDS = [
	{ fieldtype: "Section Break", label: "Header & Footer Repeat" },
	{
		fieldtype: "Select",
		fieldname: "header_mode",
		label: "Header Repeat",
		options: [
			"All pages",
			"First page only",
			"Last page only",
			"First and last pages",
			"None",
		],
		default: "All pages",
	},
	{ fieldtype: "Column Break" },
	{
		fieldtype: "Select",
		fieldname: "footer_mode",
		label: "Footer Repeat",
		options: [
			"All pages",
			"First page only",
			"Last page only",
			"First and last pages",
			"None",
		],
		default: "All pages",
	},
];

const QR_FIELDS = [
	{ fieldtype: "Section Break", label: "QR / Barcode" },
	{ fieldtype: "Check", fieldname: "include_qr", label: "Include QR Code", default: 0 },
	{
		fieldtype: "Select",
		fieldname: "qr_position",
		label: "QR Position",
		options: ["Top Right", "Top Left", "Bottom Right", "Bottom Left"],
		default: "Top Right",
		depends_on: "include_qr",
	},
	{ fieldtype: "Column Break" },
	{
		fieldtype: "Select",
		fieldname: "qr_source",
		label: "QR Data",
		options: ["Verified QR Link", "Document URL", "Custom Text"],
		default: "Verified QR Link",
		depends_on: "include_qr",
	},
	{
		fieldtype: "Data",
		fieldname: "qr_custom_text",
		label: "Custom QR Text",
		depends_on: "eval:doc.include_qr && doc.qr_source === 'Custom Text'",
	},
	{
		fieldtype: "Check",
		fieldname: "qr_force_insert",
		label: "Always add (even if one exists)",
		default: 0,
		depends_on: "include_qr",
		description:
			"Skip detection and always inject. Print formats using qr_img() are auto-detected.",
	},
];

const SIGNATURE_FIELDS = [
	{ fieldtype: "Section Break", label: "Signature Block" },
	{
		fieldtype: "Check",
		fieldname: "append_signature",
		label: "Append Signature Block",
		default: 0,
		description: "Adds a visible Acrobat-style signature card to the PDF body",
	},
	{
		fieldtype: "Select",
		fieldname: "signature_position",
		label: "Signature Position",
		options: ["End of document", "Top of document"],
		default: "End of document",
		depends_on: "append_signature",
		description: "Uses the Verified QR for this document. Silently skipped if none.",
	},
	{ fieldtype: "Column Break" },
	{
		fieldtype: "Check",
		fieldname: "apply_pades",
		label: "Apply Cryptographic Signature (PAdES)",
		default: 0,
		description:
			"Adobe Reader shows the signature panel + integrity banner. Only active if enabled in Scan Me Settings.",
	},
];

async function fetchDialogSettings() {
	try {
		const resp = await frappe.call({
			method: "scan_me.scan_me.doctype.scan_me_settings.scan_me_settings.get_dialog_settings",
		});
		return resp.message || {};
	} catch (e) {
		// If the method isn't available (older install), default to everything visible.
		return {
			show_copies: 1,
			show_header_footer: 1,
			show_qr: 1,
			show_signature: 1,
			show_live_preview: 1,
		};
	}
}

async function openPdfDialog() {
	const ctx = getPrintContext();
	if (!ctx) {
		frappe.msgprint("Unable to detect document info.");
		return;
	}

	const settings = await fetchDialogSettings();

	const fields = [];
	if (settings.show_copies) fields.push(...COPIES_FIELDS);
	if (settings.show_header_footer) fields.push(...HEADER_FOOTER_FIELDS);
	if (settings.show_qr) fields.push(...QR_FIELDS);
	if (settings.show_signature) fields.push(...SIGNATURE_FIELDS);

	if (fields.length === 0) {
		// Admin turned everything off — show a minimal notice.
		fields.push({
			fieldtype: "HTML",
			fieldname: "empty_notice",
			options:
				'<div style="padding:20px; color:#888;">All dialog sections are hidden in Scan Me Settings. PDF will be generated with defaults.</div>',
		});
	}

	const dialog = new frappe.ui.Dialog({
		title: "Generate PDF",
		size: settings.show_live_preview ? "extra-large" : "large",
		fields,
		primary_action_label: "Download PDF",
		primary_action: () => {
			const options = collectOptions(dialog);
			window.open(buildPdfUrl(ctx, options), "_blank");
			dialog.hide();
		},
	});

	dialog.show();

	if (settings.show_live_preview) {
		setupLivePreview(dialog, ctx);
	}
}

// --- live preview wiring --------------------------------------------------

function setupLivePreview(dialog, ctx) {
	const $modalDialog = dialog.$wrapper.find(".modal-dialog");
	const $modalBody = dialog.$wrapper.find(".modal-body");

	// Widen the modal — extra-large isn't enough for a side-by-side layout
	$modalDialog.css({ "max-width": "95vw", width: "95vw" });

	// Wrap existing form into a left column, append a preview column
	const $leftCol = $('<div class="sm-pdf-options"></div>');
	$modalBody.children().appendTo($leftCol);

	const $rightCol = $(`
        <div class="sm-pdf-preview-wrap">
            <div class="sm-pdf-preview-status">Loading preview…</div>
            <iframe class="sm-pdf-preview-iframe" title="PDF preview"></iframe>
        </div>
    `);

	$modalBody.append($leftCol).append($rightCol);

	$modalBody.css({
		display: "flex",
		gap: "16px",
		height: "78vh",
		padding: "12px",
	});
	$leftCol.css({
		flex: "0 0 380px",
		"overflow-y": "auto",
		"padding-right": "8px",
		"border-right": "1px solid #e5e7eb",
	});
	$rightCol.css({
		flex: "1",
		position: "relative",
		background: "#f3f4f6",
		"border-radius": "4px",
		overflow: "hidden",
	});
	$rightCol.find(".sm-pdf-preview-iframe").css({
		width: "100%",
		height: "100%",
		border: "0",
		background: "white",
	});
	$rightCol.find(".sm-pdf-preview-status").css({
		position: "absolute",
		top: "8px",
		left: "12px",
		right: "12px",
		padding: "6px 10px",
		background: "rgba(17,24,39,0.85)",
		color: "white",
		"font-size": "12px",
		"border-radius": "3px",
		"z-index": 10,
		display: "none",
	});

	// --- preview refresh loop -------------------------------------------
	let debounceTimer = null;
	let currentBlobUrl = null;
	let activeController = null;
	const $iframe = $rightCol.find(".sm-pdf-preview-iframe");
	const $status = $rightCol.find(".sm-pdf-preview-status");

	const refreshPreview = () => {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(renderPreview, 600);
	};

	const renderPreview = async () => {
		if (activeController) activeController.abort();
		activeController = new AbortController();
		$status.text("Rendering preview…").show();

		const options = collectOptions(dialog);
		try {
			const resp = await fetch(buildPdfUrl(ctx, options), {
				signal: activeController.signal,
				credentials: "same-origin",
			});
			if (!resp.ok) {
				const txt = await resp.text();
				throw new Error(`HTTP ${resp.status}: ${txt.slice(0, 200)}`);
			}
			const blob = await resp.blob();
			const newUrl = URL.createObjectURL(blob);
			$iframe.attr("src", newUrl);
			if (currentBlobUrl) URL.revokeObjectURL(currentBlobUrl);
			currentBlobUrl = newUrl;
			$status.hide();
		} catch (err) {
			if (err.name === "AbortError") return;
			$status.text("Preview failed: " + (err.message || err)).show();
		}
	};

	// --- change detection -----------------------------------------------
	$leftCol.on("change input", "input, select, textarea", refreshPreview);

	// Initial render
	refreshPreview();

	// Cleanup on hide
	dialog.$wrapper.on("hide.bs.modal", () => {
		clearTimeout(debounceTimer);
		if (activeController) activeController.abort();
		if (currentBlobUrl) URL.revokeObjectURL(currentBlobUrl);
	});
}
