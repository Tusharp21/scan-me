// Adds an "Advanced Print" entry to every allowlisted doctype's form toolbar.
// Uses Frappe's form API (add_action_icon if available, otherwise add_menu_item)
// so the entry survives re-renders and appears on every SPA visit.
(function () {
	function ready() {
		return window.frappe && frappe.ui && frappe.ui.form && frappe.ui.form.Form;
	}
	if (!ready()) {
		const wait = setInterval(() => {
			if (ready()) {
				clearInterval(wait);
				patch();
			}
		}, 250);
		return;
	}
	patch();

	function patch() {
		let integration_cache = null;
		let integration_promise = null;
		let cached_at = 0;
		const TTL = 60 * 1000;

		function get_integration() {
			const now = Date.now();
			if (integration_cache && now - cached_at < TTL) {
				return Promise.resolve(integration_cache);
			}
			if (integration_promise) return integration_promise;
			integration_promise = frappe
				.call({
					method: "scan_me.scan_me.doctype.scan_me_settings.scan_me_settings.get_form_integration",
					no_spinner: true,
				})
				.then((r) => {
					const msg = r.message || {};
					integration_cache = {
						allowed: new Set(msg.allowed_doctypes || []),
						show_button: !!msg.show_advanced_print_button,
					};
					cached_at = Date.now();
					integration_promise = null;
					return integration_cache;
				})
				.catch(() => {
					integration_cache = { allowed: new Set(), show_button: false };
					cached_at = Date.now();
					integration_promise = null;
					return integration_cache;
				});
			return integration_promise;
		}

		const original_refresh = frappe.ui.form.Form.prototype.refresh;
		frappe.ui.form.Form.prototype.refresh = function () {
			const ret = original_refresh.apply(this, arguments);
			maybe_add_entry(this);
			return ret;
		};

		function maybe_add_entry(frm) {
			if (!frm || !frm.doctype || !frm.doc) return;
			if (frm.is_new && frm.is_new()) return;
			get_integration().then((cfg) => {
				if (!cfg.show_button) return;
				if (!cfg.allowed.has(frm.doctype)) return;
				add_menu_item(frm);
				add_toolbar_icon(frm);
			});
		}

		function go(frm) {
			frappe.set_route("scan-me-print", frm.doctype, frm.docname);
		}

		function add_menu_item(frm) {
			// Menu item under the ⋮ dropdown — 100% reliable.
			if (frm.__sm_hardcopy_menu) return;
			try {
				frm.page.add_menu_item(
					__("Advanced Print (Scan Me)"),
					() => go(frm),
					true // standard
				);
				frm.__sm_hardcopy_menu = true;
			} catch (_e) {
				/* ignore */
			}
		}

		function add_toolbar_icon(frm) {
			// Always DOM-inject a distinctive document icon — avoid Frappe's
			// native "printer" icon name which would duplicate the standard
			// print button visually.
			inject_dom_icon(frm);
		}

		function find_print_button($wrapper) {
			// Match Frappe's print icon regardless of tooltip implementation.
			const print_label = __("Print");
			return $wrapper
				.find(".page-actions button")
				.filter(function () {
					const t =
						this.getAttribute("data-original-title") ||
						this.getAttribute("title") ||
						"";
					return t === "Print" || t === print_label;
				})
				.first();
		}

		function build_button(frm) {
			const $btn = $(
				'<button class="btn btn-default icon-btn sm-hardcopy-btn" type="button"' +
					' title="' +
					__("Advanced Print (Scan Me)") +
					'">' +
					'<svg viewBox="0 0 24 24" width="14" height="14" fill="none"' +
					' stroke="currentColor" stroke-width="2" stroke-linecap="round"' +
					' stroke-linejoin="round">' +
					'<rect x="5" y="3" width="14" height="18" rx="2"></rect>' +
					'<line x1="8" y1="7" x2="16" y2="7"></line>' +
					'<line x1="8" y1="11" x2="16" y2="11"></line>' +
					'<line x1="8" y1="15" x2="12" y2="15"></line>' +
					"</svg></button>"
			);
			$btn.on("click", () => go(frm));
			return $btn;
		}

		function inject_dom_icon(frm) {
			if (!frm.page || !frm.page.wrapper) return;
			const $wrapper = frm.page.wrapper;
			const $existing = $wrapper.find(".sm-hardcopy-btn");
			const $printBtn = find_print_button($wrapper);

			// Already placed — make sure it's sitting right after Print if Print
			// has since appeared. Otherwise leave it alone.
			if ($existing.length) {
				if ($printBtn.length && !$printBtn.next().is(".sm-hardcopy-btn")) {
					$existing.detach();
					$printBtn.after($existing);
				}
				return;
			}

			const $btn = build_button(frm);

			// Preferred: slot in right after Frappe's native Print icon.
			if ($printBtn.length) {
				$printBtn.after($btn);
				return;
			}

			// Fallback: end of custom-actions / page-actions so the icon still
			// appears on forms where the Print icon isn't exposed yet (it'll be
			// repositioned next to Print on the next refresh if Print appears).
			let $group = $wrapper.find(".page-actions .custom-actions").first();
			if (!$group.length) $group = $wrapper.find(".page-actions").first();
			if ($group.length) $group.append($btn);
		}

		// Re-apply on every route change — ensures we catch cases where the
		// prototype wrap is bypassed (e.g., page cached and restored).
		if (frappe.router && typeof frappe.router.on === "function") {
			frappe.router.on("change", () => {
				setTimeout(() => {
					if (window.cur_frm) maybe_add_entry(window.cur_frm);
				}, 300);
			});
		}
	}
})();
