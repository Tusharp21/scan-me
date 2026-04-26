# Scan Me

A Frappe app that turns any allowlisted document into a verifiable, signable PDF — with a Chromium-based PDF pipeline, QR-backed verification, optional content hashing, and PAdES digital signatures recognised by Adobe Acrobat.

## Features

- Verified QR per signed document (UUIDv4 + optional SHA-256 content hash + signatory metadata).
- Public verify page at `/verify_document/` with a camera scanner that returns valid / tampered / invalid for any QR.
- Chromium PDF pipeline (Playwright) with full modern CSS support.
- Live-preview print dialog with iframe that regenerates on every option change.
- Multi-copy PDF (1–5 copies) with `ORIGINAL` / `DUPLICATE` / custom labels.
- Per-page header/footer modes: all pages / first only / last only / first+last / none.
- Dialog-driven QR insertion in any of four corners.
- Acrobat-style signature block rendered as an Acrobat Sign-style card.
- PAdES digital signatures via PyHanko, Adobe-compatible.
- Lockable audit trail with optional absolute lock on Verified QR records.
- Jinja helpers: `qr`, `barcode`, `qr_link`, `qr_img`, `qr_link_img`, `verify_qr`, `verify_qr_img`.
- Bundled Sales Invoice Scan Me print format.

## Installation

```bash
bench get-app scan_me
bench install-app scan_me
```

Playwright's Chromium browser is downloaded automatically by the `after_install` hook so PDF generation works immediately.

### Fallback — manual Chromium install

If the auto-download fails, run this once on the server:

```bash
./env/bin/python -m playwright install chromium
```

### Python dependencies

- qrcode
- python-barcode
- playwright
- pypdf
- pyHanko
- cryptography

All install automatically via `bench install-app`.

## Configuration

Open Scan Me Settings in the desk:

1. Under Doctype, add the DocTypes you want to expose for QR signing. Tick `enable` for each; tick `signature_required` if users must draw a signature before generating the QR.
2. Under Verification & Signing, configure:
   - Allow Multiple Signers — N-party signing.
   - Embed Content Hash in QR — tamper detection on doc edits.
   - Lock Verified QR After Insert — absolute lock, no override.
   - Use Stored User Signature Only — reads from a User custom field named `user_signature` / `signature` / `signature_image`.
   - Apply Cryptographic PDF Signature (PAdES) — run every generated PDF through PyHanko.
3. Under Print Dialog Features, toggle which sections of the print dialog your users see.

### PAdES configuration

The first time PAdES signing runs, Scan Me auto-generates a 5-year self-signed PKCS#12 at `sites/<site>/private/files/scan_me/signing.pfx` and stores its password in `site_config.json` under `scan_me_signing_password`.

To upgrade to a CA-issued certificate:

1. Obtain a PKCS#12 bundle from a trusted CA.
2. Replace `sites/<site>/private/files/scan_me/signing.pfx` with the new file.
3. Update `scan_me_signing_password` in `site_config.json` to the bundle's password.

## Usage

### Sign a document

1. Open a doc of an allowlisted DocType.
2. Click Generate Verified QR in the form's menu.
3. Draw a signature if prompted. A Verified QR record is created.

### Generate a PDF

1. Menu → Print → select a print format.
2. Click the Generate PDF button in the toolbar.
3. Configure copies, header/footer, QR, signature block, PAdES signing.
4. Download PDF.

### Verify a QR

- Open the verify page on a phone or laptop with a camera.
- Scan the QR on the printed/PDF document.
- Page shows valid (green), tampered (red, hash mismatch), or invalid (UUID unknown).

## License

MIT — see `license.txt`.
