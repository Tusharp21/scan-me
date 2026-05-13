# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Print-time CSS injected into every PDF for proper table pagination."""

PRINT_CSS = """
	body { margin:0; background:white !important; }
	* {
		-webkit-print-color-adjust:exact !important;
		print-color-adjust:exact !important;
	}

	/* tables: keep header/footer repeating, but don't let a row split mid-cell */
	table { border-collapse:collapse; }
	thead { display:table-header-group; }
	tfoot { display:table-footer-group; break-inside:avoid; page-break-inside:avoid; }
	tbody { display:table-row-group; }

	/* keep each row whole — if it doesn't fit, push to next page (prevents the
	   "table not closed" look caused by Chrome cutting a row mid-content) */
	tr {
		break-inside:avoid;
		page-break-inside:avoid;
	}

	/* if a row IS forced to break (single row taller than a page),
	   redraw cell borders/background on each fragment */
	td, th {
		overflow-wrap:break-word;
		word-wrap:break-word;
		-webkit-box-decoration-break:clone;
		box-decoration-break:clone;
	}

	/* divs that break across pages — redraw border/background on every
	   fragment so the box appears "closed" on the breaking page too */
	div {
		-webkit-box-decoration-break:clone;
		box-decoration-break:clone;
	}

	/* nested wrappers inside cells — let them flow */
	td div, td p, td span {
		overflow-wrap:break-word;
		word-wrap:break-word;
	}

	h1,h2,h3,h4,h5,h6 {
		page-break-after:avoid;
		break-after:avoid;
	}

	/* ====================================================================
	   Edge-case rules — extend the base table/break behavior above.
	   Each block exists for one specific failure mode seen in real PDFs.
	   ==================================================================== */

	/* Images larger than the page (or cell) push the layout sideways and
	   break Chrome's column math. Constrain to 100% of the container so a
	   big logo or signature image scales down instead of overflowing. */
	img {
		max-width:100%;
		height:auto;
	}

	/* Avoid leaving a single line of a paragraph alone at the top or bottom
	   of a page (orphans/widows). 2 lines minimum is the print convention. */
	p {
		orphans:2;
		widows:2;
		margin:0 0 4px;
	}

	/* Same idea for table rows where the renderer supports it — modern
	   Chromium honors orphans/widows on table-row-group children too. */
	tr {
		orphans:2;
		widows:2;
	}

	/* Lists (esp. numbered Terms & Conditions) — keep each <li> whole so a
	   single bullet doesn't split into "1." on one page and the body on the
	   next. The <ul>/<ol> itself can still break between bullets. */
	li {
		break-inside:avoid;
		page-break-inside:avoid;
	}

	/* Preformatted blocks (code, ASCII art) need to wrap instead of producing
	   a horizontal scrollbar in print — Chrome will simply clip otherwise. */
	pre {
		white-space:pre-wrap;
		word-wrap:break-word;
		overflow-wrap:break-word;
	}

	/* If a <table> uses <caption>, keep it with the table — Chrome may
	   otherwise drop the caption on the previous page and the table on the
	   next, which looks like an orphan title. */
	caption {
		caption-side:top;
		break-after:avoid;
		page-break-after:avoid;
	}

	/* Long unbreakable strings — invoice numbers, IDs, URLs, hashes — that
	   have no spaces. ``overflow-wrap: anywhere`` lets the renderer break
	   inside the word at any character to keep the line within the cell. */
	a, code, .breakable {
		overflow-wrap:anywhere;
		word-break:break-word;
	}

	/* ====================================================================
	   Utility classes — opt-in controls for print-format authors. Match
	   Frappe core naming where possible (.page-break is already shipped by
	   Frappe core for "page break after"; the rest are conveniences).
	   ==================================================================== */

	/* <div class="page-break"></div> — Frappe-core convention. Forces the
	   NEXT page to start at this point. */
	.page-break {
		page-break-after:always;
		break-after:page;
	}

	/* <div class="page-break-after"></div> — explicit alias of .page-break. */
	.page-break-after {
		page-break-after:always;
		break-after:page;
	}

	/* <... class="new-page"> — start THIS element on a new page. Useful for
	   sectional content like "Terms" or "Annexure" that should always
	   begin fresh. */
	.new-page,
	.page-break-before {
		page-break-before:always;
		break-before:page;
	}

	/* <... class="no-split"> or "keep-together" — never split this element
	   across pages. If it would cross a boundary, the whole element gets
	   pushed to the next page. */
	.no-split,
	.keep-together {
		break-inside:avoid;
		page-break-inside:avoid;
	}

	/* <... class="no-print"> or data-no-print — hide entirely from PDF
	   output. Useful for screen-only debug widgets, banners, or buttons
	   that templates may include. */
	.no-print,
	[data-no-print] {
		display:none !important;
	}

	/* <... class="screen-only"> — same intent as .no-print, kept under a
	   different name because some teams already use this convention. */
	.screen-only {
		display:none !important;
	}
"""
