/* global scan_me */
frappe.provide("scan_me.pages");

frappe.pages["scan-me-print"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Advanced Print"),
		single_column: true,
	});
	scan_me.pages.print_view = new ScanMeAdvancedPrint(page);
};

frappe.pages["scan-me-print"].on_page_show = function () {
	if (scan_me.pages.print_view) scan_me.pages.print_view.on_show();
};

class ScanMeAdvancedPrint {
	constructor(page) {
		this.page = page;
		this.$wrapper = $(page.body);
		this.debounce_timer = null;
		this.current_blob_url = null;
		this.active_controller = null;
		this.fields_dict = {};
		this.settings = null;

		this.parse_route();
		if (!this.doctype || !this.docname) {
			this.render_missing_doc();
			return;
		}
		this.inject_styles();
		this.setup_page_actions();
		this.render_skeleton();
		this.load_and_init();
	}

	parse_route() {
		const route = frappe.get_route();
		this.doctype = route[1] ? decodeURIComponent(route[1]) : null;
		this.docname = route[2] ? decodeURIComponent(route[2]) : null;
		if (this.doctype && this.docname) {
			this.page.set_title(this.docname);
			this.page.set_title_sub(this.doctype);
			this.set_breadcrumbs();
		}
	}

	set_breadcrumbs() {
		if (!this.doctype || !this.docname) return;
		if (!frappe.breadcrumbs || !frappe.breadcrumbs.append_breadcrumb_element) return;

		const slug = frappe.router.slug(this.doctype);
		const route = frappe.get_route_str();

		// Tell Frappe's breadcrumb system to treat this page as "handled" so
		// its default update() doesn't hide the bar via toggle(false).
		frappe.breadcrumbs.all[route] = { type: "Custom", route: "", label: "" };

		const apply = () => {
			try {
				frappe.breadcrumbs.clear();
				frappe.breadcrumbs.append_breadcrumb_element(`/app/${slug}`, __(this.doctype));
				frappe.breadcrumbs.append_breadcrumb_element(
					`/app/${slug}/${encodeURIComponent(this.docname)}`,
					this.docname
				);
				frappe.breadcrumbs.append_breadcrumb_element("", __("Advanced Print"));
				frappe.breadcrumbs.toggle(true);
			} catch (_e) {
				/* decorative — ignore */
			}
		};
		// Frappe's update() can fire after ours (router post-init) and clobber
		// the crumbs. Re-apply at a few beats so our trail wins.
		apply();
		setTimeout(apply, 50);
		setTimeout(apply, 300);
		setTimeout(apply, 900);
	}

	on_show() {
		const route = frappe.get_route();
		const new_doctype = route[1] ? decodeURIComponent(route[1]) : null;
		const new_docname = route[2] ? decodeURIComponent(route[2]) : null;
		if (new_doctype !== this.doctype || new_docname !== this.docname) {
			this.doctype = new_doctype;
			this.docname = new_docname;
			this.parse_route();
			this.schedule_preview();
		} else {
			// Re-apply breadcrumbs — Frappe resets them on every page show.
			this.set_breadcrumbs();
		}
	}

	setup_page_actions() {
		this.page.set_primary_action(__("Download PDF"), () => this.download(), "download");
		// Print toolbar actions — grouped under the ⋮ menu for a cleaner main area.
		this.page.add_menu_item(__("Print"), () => this.action_print());
		this.page.add_menu_item(__("Open in Full Page"), () => this.action_full_page());
		this.page.add_menu_item(__("Email with Attachment"), () => this.action_email());
		this.page.add_menu_item(__("Copy PDF Link"), () => this.action_copy_link());
		this.page.add_menu_item(__("Refresh Preview"), () => this.render_preview());
		this.page.add_menu_item(__("Open Standard Print View"), () => {
			frappe.set_route("print", this.doctype, this.docname);
		});
		this.page.add_menu_item(__("Back to Document"), () => {
			frappe.set_route("Form", this.doctype, this.docname);
		});
	}

	inject_styles() {
		if (document.getElementById("sm-ap-styles")) return;
		const style = document.createElement("style");
		style.id = "sm-ap-styles";
		style.textContent = SM_AP_CSS;
		document.head.appendChild(style);
	}

	render_missing_doc() {
		this.$wrapper.html(`
            <div class="sm-ap-empty">
                <p>${__("No document selected. Open this page from a document's toolbar.")}</p>
            </div>
        `);
	}

	render_skeleton() {
		this.$wrapper.html(`
            <div class="sm-ap-layout">
                <aside class="sm-ap-sidebar">
                    <div class="sm-ap-section">
                        <div class="sm-ap-section-title">${__("Print Setup")}</div>
                        <div data-ap-field="print_format"></div>
                        <div data-ap-field="letter_head"></div>
                        <div data-ap-field="orientation"></div>
                        <div data-ap-field="language"></div>
                        <div data-ap-field="attach_to_doc"></div>
                    </div>
                    <div class="sm-ap-section" data-section="copies">
                        <div class="sm-ap-section-title">${__("Copies")}</div>
                        <div data-ap-field="copy_count"></div>
                        <div data-ap-field="copy_labels"></div>
                        <div data-ap-field="apply_watermark"></div>
                        <div data-ap-field="watermark_text"></div>
                    </div>
                    <div class="sm-ap-section" data-section="header_footer">
                        <div class="sm-ap-section-title">${__("Header & Footer Repeat")}</div>
                        <div data-ap-field="header_mode"></div>
                        <div data-ap-field="footer_mode"></div>
                    </div>
                    <div class="sm-ap-section" data-section="qr">
                        <div class="sm-ap-section-title">${__("QR / Barcode")}</div>
                        <div data-ap-field="include_qr"></div>
                        <div data-ap-field="qr_position"></div>
                        <div data-ap-field="qr_source"></div>
                        <div data-ap-field="qr_custom_text"></div>
                        <div data-ap-field="qr_force_insert"></div>
                    </div>
                    <div class="sm-ap-section" data-section="signature">
                        <div class="sm-ap-section-title">${__("Signature")}</div>
                        <div data-ap-field="apply_signature"></div>
                        <div class="sm-ap-pades-hint" hidden>
                            🔒 ${__(
								"Final PDF will be cryptographically signed (PAdES). Adobe Reader will show the signature panel — no visual stamp is drawn on the page."
							)}
                        </div>
                    </div>
                </aside>
                <section class="sm-ap-main">
                    <div class="sm-ap-preview-wrap">
                        <div class="sm-ap-badge" hidden>
                            <span class="sm-ap-spinner"></span>
                            <span class="sm-ap-badge-text">${__("Updating…")}</span>
                        </div>
                        <iframe class="sm-ap-iframe" title="${__("PDF Preview")}"></iframe>
                    </div>
                </section>
            </div>
        `);
	}

	async load_and_init() {
		try {
			const resp = await frappe.call({
				method: "scan_me.scan_me.doctype.scan_me_settings.scan_me_settings.get_dialog_settings",
			});
			this.settings = resp.message || {};
		} catch (e) {
			this.settings = {
				show_copies: 1,
				show_header_footer: 1,
				show_qr: 1,
				show_signature: 1,
				signature_type: "Visual Block",
			};
		}
		await this.load_print_defaults();
		this.build_fields();
		this.toggle_sections();
		this.schedule_preview();
	}

	async load_print_defaults() {
		try {
			const resp = await frappe.call({
				method: "scan_me.scan_me.doctype.scan_me_settings.scan_me_settings.get_print_defaults",
				args: { doctype: this.doctype },
			});
			const msg = resp.message || {};
			this.print_defaults = {
				print_format: msg.print_format || "Standard",
				letter_head: msg.letter_head || "",
			};
		} catch (e) {
			this.print_defaults = { print_format: "Standard", letter_head: "" };
		}
	}

	build_fields() {
		const defaults = this.print_defaults || { print_format: "Standard", letter_head: "" };
		this.make_field("print_format", {
			fieldtype: "Link",
			fieldname: "print_format",
			label: __("Print Format"),
			options: "Print Format",
			get_query: () => ({ filters: { doc_type: this.doctype } }),
			default: defaults.print_format,
		});
		this.make_field("letter_head", {
			fieldtype: "Link",
			fieldname: "letter_head",
			label: __("Letter Head"),
			options: "Letter Head",
			default: defaults.letter_head,
		});
		this.make_field("orientation", {
			fieldtype: "Select",
			fieldname: "orientation",
			label: __("Orientation"),
			options: ["Portrait", "Landscape"],
			default: "Portrait",
		});
		this.make_field("language", {
			fieldtype: "Link",
			fieldname: "language",
			label: __("Language"),
			options: "Language",
		});
		this.make_field("attach_to_doc", {
			fieldtype: "Check",
			fieldname: "attach_to_doc",
			label: __("Attach PDF to Document"),
			default: 0,
			description: __(
				"When on, clicking Download also saves the PDF as a private attachment on this document."
			),
		});

		this.make_field("copy_count", {
			fieldtype: "Select",
			fieldname: "copy_count",
			label: __("Number of Copies"),
			options: ["1", "2", "3", "4", "5"],
			default: "1",
		});
		this.make_field("copy_labels", {
			fieldtype: "Small Text",
			fieldname: "copy_labels",
			label: __("Copy Labels (optional)"),
			description: __(
				"Comma-separated stamps for each copy (e.g. ORIGINAL, DUPLICATE). Leave empty for plain copies without any stamp."
			),
			depends_on: "eval:doc.copy_count > 1",
		});

		// Watermark fields — visible only when the admin enabled a mode in Settings.
		const wm_mode = (this.settings && this.settings.watermark_mode) || "Disabled";
		if (wm_mode === "Document Status") {
			this.make_field("apply_watermark", {
				fieldtype: "Check",
				fieldname: "apply_watermark",
				label: __("Add Status Watermark"),
				default: 0,
				description: __("Stamps the document's current status as a background watermark."),
			});
		} else if (wm_mode === "Custom Text") {
			this.make_field("apply_watermark", {
				fieldtype: "Check",
				fieldname: "apply_watermark",
				label: __("Add Watermark"),
				default: 0,
			});
			this.make_field("watermark_text", {
				fieldtype: "Data",
				fieldname: "watermark_text",
				label: __("Watermark Text"),
				depends_on: "apply_watermark",
				description: __(
					"Text stamped diagonally across every page (e.g. CONFIDENTIAL, SAMPLE, DRAFT)."
				),
			});
		}

		const hf = [
			"All pages",
			"First page only",
			"Last page only",
			"First and last pages",
			"None",
		];
		this.make_field("header_mode", {
			fieldtype: "Select",
			fieldname: "header_mode",
			label: __("Header Repeat"),
			options: hf,
			default: "All pages",
		});
		this.make_field("footer_mode", {
			fieldtype: "Select",
			fieldname: "footer_mode",
			label: __("Footer Repeat"),
			options: hf,
			default: "All pages",
		});

		this.make_field("include_qr", {
			fieldtype: "Check",
			fieldname: "include_qr",
			label: __("Include QR Code"),
			default: 0,
		});
		this.make_field("qr_position", {
			fieldtype: "Select",
			fieldname: "qr_position",
			label: __("QR Position"),
			options: ["Top Right", "Top Left", "Bottom Right", "Bottom Left"],
			default: "Top Right",
			depends_on: "include_qr",
		});
		this.make_field("qr_source", {
			fieldtype: "Select",
			fieldname: "qr_source",
			label: __("QR Data"),
			options: ["Verified QR Link", "Document URL", "Custom Text"],
			default: "Verified QR Link",
			depends_on: "include_qr",
		});
		this.make_field("qr_custom_text", {
			fieldtype: "Data",
			fieldname: "qr_custom_text",
			label: __("Custom QR Text"),
			depends_on: "eval:doc.include_qr && doc.qr_source === 'Custom Text'",
		});
		this.make_field("qr_force_insert", {
			fieldtype: "Check",
			fieldname: "qr_force_insert",
			label: __("Always add (even if one exists)"),
			default: 0,
			depends_on: "include_qr",
		});

		this.make_field("apply_signature", {
			fieldtype: "Check",
			fieldname: "apply_signature",
			label: __("Apply Signature"),
			default: 0,
		});

		Object.values(this.fields_dict).forEach((f) => {
			f.df.change = () => this.on_field_change();
		});
		this.refresh_depends_on();
		this.update_pades_hint();
		this.update_orientation_class();
	}

	update_orientation_class() {
		const v = this.fields_dict.orientation && this.fields_dict.orientation.get_value();
		this.$wrapper.find(".sm-ap-iframe").toggleClass("sm-ap-landscape", v === "Landscape");
	}

	make_field(key, df) {
		const $slot = this.$wrapper.find(`[data-ap-field="${key}"]`);
		if (!$slot.length) return;
		const control = frappe.ui.form.make_control({
			df: df,
			parent: $slot[0],
			render_input: true,
		});
		if ("default" in df) control.set_value(df.default);
		this.fields_dict[key] = control;
	}

	toggle_sections() {
		const s = this.settings;
		this.$wrapper.find('[data-section="copies"]').toggle(!!s.show_copies);
		this.$wrapper.find('[data-section="header_footer"]').toggle(!!s.show_header_footer);
		this.$wrapper.find('[data-section="qr"]').toggle(!!s.show_qr);
		this.$wrapper.find('[data-section="signature"]').toggle(!!s.show_signature);
	}

	on_field_change() {
		this.refresh_depends_on();
		this.update_pades_hint();
		this.update_orientation_class();
		this.schedule_preview();
	}

	update_pades_hint() {
		// Hint is meaningful only when (a) Apply Signature is on, (b) the
		// configured signature_type involves PAdES, and (c) the admin master
		// switch enable_pades_signing is on — otherwise PAdES silently downgrades.
		const values = this.collect_values();
		const sig_type = (this.settings && this.settings.signature_type) || "Visual Block";
		const pades_enabled = !!(this.settings && this.settings.enable_pades_signing);
		const apply = !!values.apply_signature;
		const wants_pades = sig_type === "Cryptographic (PAdES)" || sig_type === "Both";
		const show = apply && wants_pades && pades_enabled;
		this.$wrapper.find(".sm-ap-pades-hint").prop("hidden", !show);
	}

	refresh_depends_on() {
		const values = this.collect_values();
		Object.values(this.fields_dict).forEach((control) => {
			const dep = control.df.depends_on;
			if (!dep) return;
			let visible = true;
			if (typeof dep === "string" && dep.startsWith("eval:")) {
				try {
					visible = Function("doc", `return (${dep.slice(5)});`)(values);
				} catch (e) {
					visible = true;
				}
			} else if (typeof dep === "string") {
				visible = !!values[dep];
			}
			$(control.wrapper).toggle(!!visible);
		});
	}

	collect_values() {
		const v = {};
		for (const [k, f] of Object.entries(this.fields_dict)) {
			if (f.get_value) v[k] = f.get_value();
		}
		return v;
	}

	build_options(v) {
		// Map the single "Apply Signature" checkbox to the underlying API flags
		// based on the signature_type configured in Scan Me Settings.
		const sig_type = (this.settings && this.settings.signature_type) || "Visual Block";
		const apply = !!v.apply_signature;
		const want_visual = apply && (sig_type === "Visual Block" || sig_type === "Both");
		const want_pades = apply && (sig_type === "Cryptographic (PAdES)" || sig_type === "Both");

		// Resolve the watermark payload from the configured mode.
		const wm_mode = (this.settings && this.settings.watermark_mode) || "Disabled";
		let watermark_text = "";
		if (v.apply_watermark) {
			if (wm_mode === "Document Status") {
				watermark_text = "__status__";
			} else if (wm_mode === "Custom Text") {
				watermark_text = (v.watermark_text || "").trim();
			}
		}

		return {
			copy_count: parseInt(v.copy_count || "1", 10),
			copy_labels: v.copy_labels || "",
			orientation: v.orientation || "Portrait",
			header_mode: v.header_mode || "All pages",
			footer_mode: v.footer_mode || "All pages",
			include_qr: v.include_qr ? 1 : 0,
			qr_position: v.qr_position || "Top Right",
			qr_source: v.qr_source || "Verified QR Link",
			qr_custom_text: v.qr_custom_text || "",
			qr_force_insert: v.qr_force_insert ? 1 : 0,
			append_signature: want_visual ? 1 : 0,
			apply_pades: want_pades ? 1 : 0,
			watermark_text: watermark_text,
			attach_to_doc: v.attach_to_doc ? 1 : 0,
		};
	}

	build_pdf_url(v, { preview = false } = {}) {
		const params = new URLSearchParams({
			doctype: this.doctype,
			name: this.docname,
			print_format: v.print_format || "Standard",
			options: JSON.stringify(this.build_options(v)),
		});
		if (v.letter_head) params.set("letter_head", v.letter_head);
		if (v.language) params.set("_lang", v.language);
		if (preview) params.set("preview_mode", "1");
		return `/api/method/scan_me.api.pdf.generate_chrome_pdf?${params.toString()}`;
	}

	schedule_preview() {
		clearTimeout(this.debounce_timer);
		this.debounce_timer = setTimeout(() => this.render_preview(), 600);
	}

	async render_preview() {
		const $iframe = this.$wrapper.find(".sm-ap-iframe");
		if (!$iframe.length) return;

		if (this.active_controller) this.active_controller.abort();
		this.active_controller = new AbortController();
		this.show_badge(__("Updating…"), "info");

		try {
			const values = this.collect_values();
			const url = this.build_pdf_url(values, { preview: true });
			const resp = await fetch(url, {
				signal: this.active_controller.signal,
				credentials: "same-origin",
			});
			if (!resp.ok) {
				const txt = await resp.text();
				throw new Error(`HTTP ${resp.status}: ${txt.slice(0, 200)}`);
			}
			const blob = await resp.blob();
			const new_url = URL.createObjectURL(blob);
			// Swap src once; the old PDF stays visible until the new one paints.
			$iframe.attr("src", new_url);
			if (this.current_blob_url) URL.revokeObjectURL(this.current_blob_url);
			this.current_blob_url = new_url;
			this.hide_badge();
		} catch (err) {
			if (err.name === "AbortError") return;
			this.show_badge(__("Preview failed: {0}", [err.message || err]), "error");
		}
	}

	show_badge(msg, kind) {
		const $badge = this.$wrapper.find(".sm-ap-badge");
		$badge.find(".sm-ap-badge-text").text(msg);
		$badge.attr("data-kind", kind || "info").prop("hidden", false);
	}
	hide_badge() {
		this.$wrapper.find(".sm-ap-badge").prop("hidden", true);
	}

	// ---- toolbar actions --------------------------------------------------

	download() {
		// Download path — no preview_mode, so PAdES signing runs if enabled.
		const values = this.collect_values();
		if (values.attach_to_doc) {
			frappe.show_alert({
				message: __("PDF will also be attached to the document"),
				indicator: "blue",
			});
		}
		window.open(this.build_pdf_url(values, { preview: false }), "_blank");
	}

	action_print() {
		const iframe = this.$wrapper.find(".sm-ap-iframe").get(0);
		if (!iframe) return;
		try {
			iframe.contentWindow.focus();
			iframe.contentWindow.print();
		} catch (_e) {
			window.open(this.build_pdf_url(this.collect_values()), "_blank");
		}
	}

	action_full_page() {
		if (this.current_blob_url) {
			window.open(this.current_blob_url, "_blank");
			return;
		}
		window.open(this.build_pdf_url(this.collect_values()), "_blank");
	}

	async action_copy_link() {
		const url = new URL(
			this.build_pdf_url(this.collect_values(), { preview: false }),
			window.location.origin
		).href;
		try {
			await navigator.clipboard.writeText(url);
			frappe.show_alert({ message: __("PDF link copied to clipboard"), indicator: "green" });
		} catch (_e) {
			frappe.msgprint({ title: __("Copy failed"), message: url, indicator: "blue" });
		}
	}

	action_email() {
		new frappe.views.CommunicationComposer({
			doc: { doctype: this.doctype, name: this.docname },
			subject: __("{0}: {1}", [this.doctype, this.docname]),
			recipients: "",
			attach_document_print: true,
			message: __("Please find the attached {0}.", [this.doctype]),
		});
	}
}

const SM_AP_CSS = `
.sm-ap-layout {
    display: grid;
    grid-template-columns: 320px 1fr;
    gap: 16px;
    align-items: start;
    padding: 0 8px 32px;
}
.sm-ap-sidebar {
    position: sticky;
    top: 80px;
    align-self: start;
    max-height: calc(100vh - 120px);
    overflow-y: auto;
    padding-right: 4px;
}
.sm-ap-section {
    background: var(--card-bg, #fff);
    border: 1px solid var(--border-color, #e5e7eb);
    border-radius: 8px;
    padding: 14px 16px;
    margin-bottom: 12px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}
.sm-ap-section-title {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted, #6b7280);
    margin: 0 0 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border-color, #e5e7eb);
}
.sm-ap-section .frappe-control {
    margin-bottom: 10px;
}
.sm-ap-section .frappe-control:last-child {
    margin-bottom: 0;
}
.sm-ap-pades-hint {
    margin-top: 8px;
    padding: 8px 10px;
    background: var(--bg-blue-50, #eff6ff);
    border: 1px solid var(--blue-200, #bfdbfe);
    border-radius: 6px;
    color: var(--blue-700, #1d4ed8);
    font-size: 12px;
    line-height: 1.4;
}
.sm-ap-pades-hint[hidden] { display: none; }

.sm-ap-main { position: relative; }
.sm-ap-preview-wrap {
    position: relative;
    background: var(--control-bg, #f3f4f6);
    border: 1px solid var(--border-color, #e5e7eb);
    border-radius: 8px;
    padding: 12px;
    min-height: 600px;
    display: flex;
    justify-content: center;
    align-items: flex-start;
}
.sm-ap-iframe {
    width: 100%;
    max-width: 900px;
    transition: max-width 0.2s ease;
    min-height: calc(100vh - 180px);
    height: calc(100vh - 180px);
    border: 0;
    background: white;
    border-radius: 4px;
    box-shadow: 0 2px 12px rgba(15, 23, 42, 0.1);
    display: block;
}
/* Landscape A4 is ~1.41× wider than portrait — give the preview room to fill
   the main column instead of staying boxed at the portrait width. */
.sm-ap-iframe.sm-ap-landscape {
    max-width: 1240px;
}

.sm-ap-badge {
    position: absolute;
    top: 20px;
    right: 24px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: rgba(17, 24, 39, 0.88);
    color: white;
    font-size: 12px;
    font-weight: 500;
    border-radius: 20px;
    z-index: 20;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.15);
    pointer-events: none;
    transition: opacity 0.15s ease;
}
.sm-ap-badge[hidden] { display: none; }
.sm-ap-badge[data-kind="error"] { background: #dc2626; }
.sm-ap-spinner {
    width: 12px;
    height: 12px;
    border: 2px solid rgba(255, 255, 255, 0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: sm-ap-spin 0.7s linear infinite;
}
.sm-ap-badge[data-kind="error"] .sm-ap-spinner { display: none; }
@keyframes sm-ap-spin {
    to { transform: rotate(360deg); }
}

.sm-ap-empty {
    padding: 40px;
    text-align: center;
    color: var(--text-muted, #6b7280);
}

@media (max-width: 900px) {
    .sm-ap-layout {
        grid-template-columns: 1fr;
    }
    .sm-ap-sidebar {
        position: static;
        max-height: none;
    }
    .sm-ap-iframe {
        height: 70vh;
    }
}
`;
