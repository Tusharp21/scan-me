# Scan Me

A Frappe app that turns any allowlisted document into a **verifiable, signable PDF** — with a Chromium-based PDF pipeline, QR-backed verification, optional content hashing, and real PAdES digital signatures recognised by Adobe Acrobat.

## Features

- **Verified QR** — a tamper-evident record per signed document. UUIDv4 + optional SHA-256 content hash + signatory metadata.
- **Public verify page** at `/verify_document/` — camera scanner that returns `valid` / `tampered` / `invalid` for any QR.
- **Chromium PDF pipeline** — renders Frappe print formats via headless Chromium (Playwright) instead of wkhtmltopdf. Modern CSS, flex/grid, web fonts, all work.
- **Live-preview print dialog** — an in-browser preview iframe that regenerates on every option change.
- **Multi-copy PDF** — 1–5 copies in one PDF, each stamped with `ORIGINAL` / `DUPLICATE` / custom labels.
- **Per-page header/footer modes** — all pages / first only / last only / first+last / none. Letterhead + copy badge respects the mode.
- **Dialog-driven QR insertion** — overlay a Verified QR in any of four corners. Auto-detects existing `scan-me-qr` markers to avoid double-insertion.
- **Acrobat-style signature block** — Verified QRs render as an Acrobat Sign-style card in the PDF with handwritten signature, signatory details, content hash, tamper status.
- **PAdES digital signatures (PyHanko)** — optional cryptographic signing that Adobe Reader recognises. Self-signed cert auto-generated on first use; drop a CA-issued PKCS#12 to graduate to the green "Signed and all signatures are valid" badge.
- **Lockable audit trail** — optional absolute lock on Verified QR records (no override, even for Administrator).
- **Jinja helpers** — `qr`, `barcode`, `qr_link`, `qr_img`, `qr_link_img`, `verify_qr`, `verify_qr_img` for use in any print format.
- **Sales Invoice Scan Me** — bundled print format covering company/customer info, item description, HSN, per-line discount + net rate, tax breakdown, totals, payment schedule, bank, terms, and the scan-to-verify QR.

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/Tusharp21/scan_me.git
bench install-app scan_me
```

### Post-install (required once)

Scan Me uses Playwright's Chromium for PDF rendering. Download the browser once per bench:

```bash
./env/bin/playwright install chromium
```

This is a one-time ~200 MB download. Without it, PDF generation will fail with a helpful Playwright error.

### Python dependencies

The app pins:

- `qrcode~=8.2` — QR generation
- `python-barcode~=0.16.1` — CODE128 and friends
- `playwright~=1.47` — Chromium PDF rendering
- `pypdf~=6.1.3` — PDF concatenation for multi-copy
- `pyHanko~=0.25` — PAdES digital signatures
- `cryptography>=41` — self-signed cert generation

All install automatically via `bench install-app`.

## Configuration

Go to **Scan Me Settings** (desk) and:

1. Under **Doctype**, add the DocTypes you want to expose for QR signing (e.g. `Sales Invoice`, `Purchase Order`). Tick `enable` for each; tick `signature_required` if users must draw a signature before generating the QR.
2. Under **Verification & Signing**, decide:
   - **Allow Multiple Signers** — N-party signing.
   - **Embed Content Hash in QR** — tamper detection on doc edits.
   - **Lock Verified QR After Insert** — absolute lock, no override.
   - **Use Stored User Signature Only** — rejects client images; reads from a User custom field named `user_signature` / `signature` / `signature_image` (in that order).
   - **Apply Cryptographic PDF Signature (PAdES)** — run every generated PDF through PyHanko.
3. Under **Print Dialog Features**, toggle which sections of the print dialog your users see.

### PAdES: go from yellow to green in Adobe

The first time PAdES signing runs, Scan Me auto-generates a 5-year self-signed PKCS#12 at `sites/<site>/private/files/scan_me/signing.pfx` and stores its password in `site_config.json` under `scan_me_signing_password`.

Adobe Reader will show a **yellow** "signer's identity is unknown" banner until users manually trust the cert — or you replace the PKCS#12 with a CA-issued bundle. To upgrade:

1. Obtain a PKCS#12 bundle from a trusted CA (eMudhra, Sectigo, DigiCert, etc.).
2. Replace `sites/<site>/private/files/scan_me/signing.pfx` with the new file.
3. Update `scan_me_signing_password` in `site_config.json` to the bundle's password.
4. No code change required — the next signed PDF will use the new cert and Adobe will show **green**.

## Usage

### Sign a document

1. Open a doc of an allowlisted DocType (e.g. a Sales Invoice).
2. Click **Generate Verified QR** in the form's menu.
3. Draw a signature if prompted. A Verified QR record is created; content hash + signer identity captured per your settings.

### Generate a PDF

1. Menu → Print → select a print format (the bundled "Sales Invoice Scan Me" works out of the box).
2. Click the blue **Generate PDF** button in the toolbar — opens the Scan Me dialog.
3. Configure copies, header/footer, QR, signature block, PAdES signing. Watch the iframe preview update live.
4. **Download PDF**.

### Verify a QR

- Open `https://<site>/verify_document/` on a phone or laptop with a camera.
- Scan the QR on the printed/PDF document.
- Page shows `valid` (green), `tampered` (red, hash mismatch), or `invalid` (UUID unknown).

## Jinja helpers for print formats

```jinja
{# Any string #}
{{ qr("encode-me") }}                        {# returns data URI #}
{{ barcode("12345", "code128") }}            {# returns data URI #}

{# With class="scan-me-qr" marker — print dialog skips adding a second QR #}
{{ qr_link_img(doc.doctype, doc.name) }}     {# desk URL #}
{{ verify_qr_img(doc.doctype, doc.name) }}   {# Verified QR payload, empty if doc unsigned #}
```

## Security posture (as of current release)

See `docs/security.md` for the full threat model. Short version:

- ✅ Rate-limited public verify endpoint.
- ✅ SHA-256 content hashing when enabled — edits after signing auto-invalidate.
- ✅ Absolute lock on Verified QR records when enabled — no role can override.
- ✅ Path-traversal safe: image URLs in print formats can't escape `sites/<site>/*/files/` or bench `assets/`.
- ✅ Size/format validation on client-supplied signature images (PNG/JPEG, max 2 MB).
- ✅ PAdES: real PDF signatures via PyHanko, Adobe-compatible.
- ⚠ Without CA-issued cert, Adobe shows "unknown signer" — manual trust required per reader.
- ⚠ No RFC-3161 trusted timestamp yet — `signed_on` is the server clock.

Tier 2 (HMAC + revocation) and Tier 3 (Aadhaar eSign / hardware tokens) are on the roadmap.

## Contributing

This app uses `pre-commit` for formatting and linting:

```bash
cd apps/scan_me
pre-commit install
```

Tools: `ruff`, `eslint`, `prettier`, `pyupgrade`. CI runs Frappe Semgrep Rules + `pip-audit` on PRs.

## License

MIT — see `license.txt`.
