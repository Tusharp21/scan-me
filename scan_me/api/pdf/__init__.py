# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Chrome-PDF generation pipeline for the Scan Me Advanced Print page.

Public surface kept stable for the JS endpoint
``/api/method/scan_me.api.pdf.generate_chrome_pdf`` — the function is defined
in :mod:`.generator` and re-exported here so the import path stays unchanged.

Feature modules:

* :mod:`.options`     — JSON options parsing, copy-label expansion
* :mod:`.images`      — base64 embedding for img-src / CSS url()
* :mod:`.letterhead`  — Letter Head reads, header/footer templates,
                        body-defined ``id="header-html"`` extraction,
                        Chrome-margin height measurement
* :mod:`.qr`          — optional QR code injection
* :mod:`.watermark`   — diagonal text watermark
* :mod:`.signature`   — per-page 'Signature valid/invalid' stamp
* :mod:`.pades`       — PAdES digital signing (PyHanko)
* :mod:`.assembly`    — multi-copy + header/footer mode merging
* :mod:`.attach`      — save rendered PDF as a File on the source doc
* :mod:`.css`         — print-time CSS for table pagination
* :mod:`.generator`   — @frappe.whitelist orchestrator
"""

from .generator import generate_chrome_pdf

__all__ = ["generate_chrome_pdf"]
