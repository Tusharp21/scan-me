/* global Html5Qrcode */
(function () {
	"use strict";

	var scanner = null;
	var $scanWrap = document.getElementById("scanner-wrap");
	var $scanBtn = document.getElementById("scan-btn");
	var $scanLabel = document.getElementById("scan-btn-label");
	var $stopBtn = document.getElementById("stop-btn");
	var $input = document.getElementById("uuid-input");
	var $form = document.getElementById("manual-form");
	var $result = document.getElementById("result");

	$scanBtn.addEventListener("click", startScan);
	$stopBtn.addEventListener("click", stopScan);
	$form.addEventListener("submit", function (e) {
		e.preventDefault();
		var value = ($input.value || "").trim();
		if (!value) {
			flashInput();
			return;
		}
		verify(value);
	});

	// ---- scanning ------------------------------------------------------

	function startScan() {
		if (typeof Html5Qrcode === "undefined") {
			renderState("invalid", {
				message: "QR scanner failed to load. Use the manual entry option below.",
			});
			return;
		}
		if (scanner) return;
		$scanWrap.innerHTML = "";
		$scanWrap.classList.add("active");
		scanner = new Html5Qrcode("scanner-wrap");

		Html5Qrcode.getCameras()
			.then(function (cameras) {
				if (!cameras || !cameras.length) {
					renderState("invalid", {
						message: "No camera detected. Use the manual entry option below.",
					});
					cleanupScanner();
					return;
				}
				var cameraId = pickCameraId(cameras);
				setScanButton(true);
				scanner
					.start(
						cameraId,
						{ fps: 10, qrbox: { width: 240, height: 240 } },
						function (qrText) {
							stopScan().then(function () {
								verify(qrText);
							});
						},
						function (_err) {
							/* per-frame scan misses — ignore */
						}
					)
					.catch(function () {
						renderState("invalid", {
							message:
								"Unable to start the camera. Please grant permission or use manual entry.",
						});
						cleanupScanner();
					});
			})
			.catch(function () {
				renderState("invalid", {
					message:
						"Unable to access the camera. Please grant permission or use manual entry.",
				});
				cleanupScanner();
			});
	}

	function stopScan() {
		if (!scanner) return Promise.resolve();
		return scanner.stop().then(cleanupScanner).catch(cleanupScanner);
	}

	function cleanupScanner() {
		try {
			if (scanner) scanner.clear();
		} catch (_e) {
			/* ignore */
		}
		scanner = null;
		$scanWrap.classList.remove("active");
		$scanWrap.innerHTML = "";
		setScanButton(false);
	}

	function pickCameraId(cameras) {
		// Prefer rear-facing camera on mobiles.
		for (var i = 0; i < cameras.length; i++) {
			var label = (cameras[i].label || "").toLowerCase();
			if (
				label.indexOf("back") >= 0 ||
				label.indexOf("rear") >= 0 ||
				label.indexOf("environment") >= 0
			) {
				return cameras[i].id;
			}
		}
		return cameras[0].id;
	}

	function setScanButton(running) {
		$scanLabel.textContent = running ? "Scanning…" : "Scan QR Code";
		$scanBtn.disabled = running;
		$stopBtn.hidden = !running;
	}

	function flashInput() {
		$input.style.borderColor = "#dc2626";
		setTimeout(function () {
			$input.style.borderColor = "";
		}, 700);
		$input.focus();
	}

	// ---- verify --------------------------------------------------------

	function verify(code) {
		var cleaned = (code || "").trim();
		if (!cleaned) {
			flashInput();
			return;
		}

		renderLoading();

		fetch(
			"/api/method/scan_me.api.verify_document_qr.verify_document_qr?uuid=" +
				encodeURIComponent(cleaned),
			{ credentials: "same-origin", headers: { Accept: "application/json" } }
		)
			.then(function (res) {
				if (res.status === 429) {
					renderState("invalid", {
						title: "Too Many Attempts",
						message:
							"You've hit the verification rate limit. Please wait a moment and try again.",
					});
					throw new Error("rate_limited");
				}
				return res.json();
			})
			.then(function (r) {
				var d = (r && r.message) || {};
				var status = d.status || "invalid";

				if (status === "valid") {
					renderState("verified", {
						title: d.title || "Document Authentic",
						message:
							d.message ||
							"This document is authentic and has not been modified since signing.",
						details: collectDetails(d),
					});
				} else if (status === "tampered") {
					renderState("tampered", {
						title: d.title || "Signature Invalidated",
						message:
							d.message ||
							"The document has been modified after signing. The signature is no longer valid.",
						details: collectDetails(d),
					});
				} else {
					renderState("invalid", {
						title: d.title || "Not Recognised",
						message: d.message || "This code doesn't match any record in our system.",
					});
				}
			})
			.catch(function (err) {
				if (err && err.message === "rate_limited") return;
				renderState("invalid", {
					title: "Verification Unavailable",
					message:
						"The verification service could not be reached. Please try again shortly.",
				});
			});
	}

	function collectDetails(d) {
		// Map API response fields → label/value pairs, in order. Only fields
		// the API chose to return (per Public Verify Detail Level) appear.
		var pairs = [];
		if (d.ref_doctype) pairs.push(["Document Type", d.ref_doctype, true]);
		if (d.ref_docname) pairs.push(["Reference", d.ref_docname, true]);
		if (d.signed_on) pairs.push(["Signed On", d.signed_on, true]);
		if (d.signed_by_name) pairs.push(["Signed By", d.signed_by_name, true]);
		if (d.signed_by_email) pairs.push(["Email", d.signed_by_email, true]);
		if (d.unique_id) pairs.push(["Verification ID", d.unique_id, false]);
		if (d.stored_hash) pairs.push(["Signed Hash", d.stored_hash, false]);
		if (d.current_hash) pairs.push(["Current Hash", d.current_hash, false]);
		return pairs;
	}

	// ---- render --------------------------------------------------------

	function renderLoading() {
		$result.hidden = false;
		$result.textContent = "";
		var el = document.createElement("div");
		el.className = "state state-muted";
		el.innerHTML =
			'<div class="state-icon" aria-hidden="true">' +
			'<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">' +
			'<circle cx="12" cy="12" r="10"></circle><path d="M12 6v6l4 2"></path>' +
			"</svg></div>";
		var title = document.createElement("h3");
		title.className = "state-title";
		title.textContent = "Checking…";
		el.appendChild(title);
		$result.appendChild(el);
	}

	function renderState(kind, payload) {
		var templateId =
			kind === "verified"
				? "tpl-verified"
				: kind === "tampered"
				? "tpl-tampered"
				: "tpl-invalid";
		var tpl = document.getElementById(templateId);
		var node = tpl.content.firstElementChild.cloneNode(true);

		if (payload.title) {
			var t = node.querySelector(".state-title");
			if (t) t.textContent = payload.title;
		}
		var msg = node.querySelector(".state-message");
		if (msg) msg.textContent = payload.message || "";

		var dl = node.querySelector(".details");
		if (dl) {
			if (payload.details && payload.details.length) {
				payload.details.forEach(function (p) {
					var dt = document.createElement("dt");
					dt.textContent = p[0];
					var dd = document.createElement("dd");
					dd.textContent = p[1];
					if (p[2]) dd.className = "plain";
					dl.appendChild(dt);
					dl.appendChild(dd);
				});
			} else {
				dl.remove();
			}
		}

		var again = node.querySelector(".again");
		if (again) again.addEventListener("click", resetForNext);

		$result.hidden = false;
		$result.textContent = "";
		$result.appendChild(node);
		// Scroll the result into view on mobile.
		$result.scrollIntoView({ behavior: "smooth", block: "nearest" });
	}

	function resetForNext() {
		$result.hidden = true;
		$result.textContent = "";
		$input.value = "";
		window.scrollTo({ top: 0, behavior: "smooth" });
	}
})();
