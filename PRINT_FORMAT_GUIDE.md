# Print Format Authoring Guide

> Build great-looking, page-break-safe print formats that work with the Scan Me Advanced Print pipeline (Playwright + Chromium).

This guide is for **print format authors** — anyone editing a Print Format Jinja template in Frappe. It explains the patterns the Scan Me PDF engine expects, the utility classes it ships, and the gotchas that bite first-time authors.

---

## 1. The two PDF pipelines

Scan Me adds a second PDF path on top of Frappe's standard one. Both render the same print format Jinja, but produce different PDFs.

| Pipeline | Triggered by | Engine | Best for |
|---|---|---|---|
| **Standard Print** | Frappe's built-in Print button | `wkhtmltopdf` (per `pdf_generator` field on the Print Format) | Servers that already have `wkhtmltopdf` installed |
| **Advanced Print** | Scan Me's icon (right of native Print) | Headless Chromium via Playwright | Modern CSS, multi-copy, watermark, QR overlay, PAdES |

**Recommendation:** design for Advanced Print. It supports flex/grid/web fonts/box-shadow/border-radius — `wkhtmltopdf` doesn't. Templates that look right in Advanced Print also look right in Frappe's HTML print preview.

---

## 2. Template skeleton

Start from `Basic HTML Template by Scan Me` (bundled) — duplicate it from **Print Format → ⋮ → Duplicate**, retarget the doctype, then edit.

Minimum viable structure:

```html
<div class="print-format">

  <!-- (Optional) Body header — see §3 -->
  <div id="header-html">
    <h2>My Company</h2>
    <p>Invoice {{ doc.name }} — {{ frappe.format_date(doc.posting_date) }}</p>
  </div>

  <!-- Main content -->
  <h3>Bill To</h3>
  <p>{{ doc.customer_name }}</p>

  <table>
    <thead>
      <tr><th>#</th><th>Item</th><th>Qty</th><th>Rate</th><th>Amount</th></tr>
    </thead>
    <tbody>
      {% for item in doc.items %}
        <tr>
          <td>{{ loop.index }}</td>
          <td>{{ item.item_name }}</td>
          <td>{{ item.qty }}</td>
          <td>{{ frappe.format(item.rate, {"fieldtype": "Currency"}) }}</td>
          <td>{{ frappe.format(item.amount, {"fieldtype": "Currency"}) }}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>

  <!-- (Optional) Body footer — see §3 -->
  <div id="footer-html">
    <p>Authorized signatory</p>
  </div>

</div>
```

That's it — base CSS (table pagination, image overflow protection, headings-stay-with-next, etc.) is injected automatically.

---

## 3. Header / footer: two ways

You have two places to put repeating header/footer content.

### Option A — Frappe Letter Head (recommended for organisation-wide branding)

Configure the Letter Head DocType in the desk. Header HTML and Footer HTML live there. Apply by selecting the Letter Head in the Advanced Print dialog. **Pros:** centrally managed, reused across all formats. **Cons:** less per-format flexibility.

### Option B — In-body `id="header-html"` / `id="footer-html"` (recommended for per-format content)

Put `<div id="header-html">…</div>` and `<div id="footer-html">…</div>` anywhere in your template. The PDF engine:

1. **Plucks them out** of the body before rendering.
2. **Promotes them** to the repeating page header / footer that Chromium prints on every page.
3. **Auto-measures** their rendered height and reserves the right margin (so content doesn't get clipped behind them).

The body view (Frappe's HTML print preview) still shows them inline. The downloaded PDF moves them to the page margins.

**Pages numbers** — drop these spans inside `id="footer-html"` (or in the Letter Head footer):

```html
<div id="footer-html">
  Page <span class="pageNumber"></span> of <span class="totalPages"></span>
</div>
```

Chromium resolves them at render time — no Jinja substitution needed.

### ⚠ Magic classes only work inside header/footer — not the body

`pageNumber` and `totalPages` are **Chromium-specific magic classes**. Chromium only substitutes them when they appear in the PDF's `header_template` / `footer_template` — never in body content. The same applies to `date`, `title`, `url`, and `section`.

| Class | Resolves to |
|---|---|
| `pageNumber` | Current page number |
| `totalPages` | Total page count |
| `date` | Today's date |
| `title` | Document title |
| `url` | Document URL |

| Placement | Behavior |
|---|---|
| Inside `id="header-html"` or `id="footer-html"` | ✅ Resolves (engine promotes these to Chromium's header/footer templates) |
| Inside Letter Head header / footer | ✅ Resolves (same promotion path) |
| Anywhere else in the body | ❌ Stays blank — Chromium doesn't see them |

If you want a "Page X of Y" indicator anywhere on the page, put it inside `id="header-html"` or `id="footer-html"` — that's the only path that triggers Chromium's substitution.

> ⚠ Don't use BOTH the Letter Head and `id="header-html"` for the same content. The body one wins; the Letter Head one is silently overridden.

---

## 4. Utility classes — your control surface

Scan Me ships a tiny set of opt-in classes for page-flow control. Use them sparingly — most pagination "just works" without them.

| Class | What it does | When to use |
|---|---|---|
| `.page-break` | Forces a page break **after** this element. | Section dividers between content blocks. |
| `.page-break-after` | Alias of `.page-break`. | Same. |
| `.new-page` / `.page-break-before` | Forces this element to **start** on a new page. | "Annexure", "Terms" pages that should always start fresh. |
| `.no-split` / `.keep-together` | Never split this element across pages. | Signature blocks, totals, mission-critical groups. |
| `.no-print` / `[data-no-print]` | Hidden from PDF (visible on screen). | Debug widgets, "Click to download" banners. |
| `.screen-only` | Same as `.no-print`. | Alternative naming if your team prefers it. |
| `.scan-me-qr` | Marks an existing QR `<img>` so the dialog's QR-injection doesn't double-add. | When you embed a QR via Jinja (see §6) and also leave "Include QR" on in the dialog. |
| `.breakable` | Allows long unbreakable strings (IDs, URLs, hashes) to break mid-character. | Cells with long order numbers, hashes, URLs. |

### Examples

```html
<!-- Force a page break after the items table -->
<table>...</table>
<div class="page-break"></div>
<h3>Terms & Conditions</h3>
...
```

```html
<!-- Keep the signature block together no matter what -->
<div class="no-split signature-block">
  <p>Authorized signatory</p>
  <img src="/files/signature.png" />
  <p>Date: {{ doc.posting_date }}</p>
</div>
```

```html
<!-- Hide a debug pane from PDF -->
<div class="no-print">DEBUG: doc.docstatus = {{ doc.docstatus }}</div>
```

```html
<!-- Long invoice number breaks cleanly in a narrow cell -->
<td class="breakable">{{ doc.name }}-{{ item.batch_no }}</td>
```

---

## 5. What's automatic — don't fight it

The injected base CSS already handles these. **Don't add your own rules** trying to "fix" them — you'll likely make it worse.

| Behavior | What's already in place |
|---|---|
| Table headers repeat on every page | `thead { display: table-header-group }` |
| Table footers repeat on every page | `tfoot { display: table-footer-group }` |
| Table rows don't split mid-cell | `tr { break-inside: avoid }` |
| Long words wrap in narrow cells | `td, th { overflow-wrap: break-word }` |
| Big images scale to fit | `img { max-width: 100%; height: auto }` |
| Code blocks wrap (no horizontal scroll) | `pre { white-space: pre-wrap }` |
| Headings stay with the following content | `h1-h6 { page-break-after: avoid }` |
| Cell borders redraw on fragmented rows | `box-decoration-break: clone` on td/th/div |
| Numbered list items stay whole | `li { break-inside: avoid }` |
| Table captions stay attached | `caption { break-after: avoid }` |
| Background colors print | `print-color-adjust: exact` |

> ⚠ Chromium has a known limit: if a single row is **taller than a page**, it will still break and the bottom border may not render on the broken fragment. The base CSS minimises this but can't eliminate it. If you have row content that big (e.g. a 9-point "Scope of Work" paragraph in a description cell), consider splitting it into multiple rows or pre-wrapping at the Jinja level.

---

## 6. Jinja helpers (QR, barcode, verify links)

Available in every print format:

```jinja
{# Pure base64 data URIs — embed as src #}
{{ qr("encode anything") }}
{{ barcode("12345", "code128") }}
{{ qr_link(doc.doctype, doc.name) }}              {# QR encoding the desk URL #}

{# Pre-built <img> with class="scan-me-qr" #}
{{ qr_img("anything") }}
{{ qr_link_img(doc.doctype, doc.name) }}

{# Verified QR (returns empty if doc is unsigned) #}
{{ verify_qr(doc.doctype, doc.name) }}            {# data URI #}
{{ verify_qr_img(doc.doctype, doc.name) }}        {# <img class="scan-me-qr"> #}
```

### Size & customization

```jinja
{# Custom size (CSS unit — mm/px/%/cm) #}
{{ qr_img("text", size="40mm") }}

{# Larger box size + colored modules #}
{{ qr("text", clearity=12, fill_color="#003366") }}

{# QR with site logo overlaid #}
{{ qr("text", include_logo=True) }}
```

### Bounds (enforced — exceeding throws ValidationError)

| Parameter | Min | Max |
|---|---|---|
| `clearity` (pixels per module) | 1 | 20 |
| `border` (quiet zone modules) | 0 | 10 |
| `size` (CSS unit) | must match `^\d+(\.\d+)?(mm|px|cm|in|%)$` | — |
| Encoded data | — | 2953 bytes (QR v40 capacity) |

### Avoiding double-QR

If you embed a Verified QR in the body **AND** leave "Include QR" on in the print dialog, the dialog detects the existing `class="scan-me-qr"` marker and skips overlay injection. This is why all our helpers ship with that class already set.

> If you want to force overlay anyway, the dialog has a **"Force insert QR"** option.

---

## 7. Patterns

### 7a. Multi-page table with section break

```html
<table>
  <thead>
    <tr><th>Sr</th><th>Item</th><th>Qty</th></tr>
  </thead>
  <tbody>
    {% for item in doc.items %}
      <tr>
        <td>{{ loop.index }}</td>
        <td>{{ item.item_name }}</td>
        <td>{{ item.qty }}</td>
      </tr>
    {% endfor %}
  </tbody>
  <tfoot>
    <tr><td colspan="2">Total</td><td>{{ doc.total_qty }}</td></tr>
  </tfoot>
</table>

<div class="page-break"></div>

<h3 class="new-page">Terms & Conditions</h3>
<ol>
  <li>...</li>
</ol>
```

### 7b. Signature block that never splits

```html
<div class="no-split" style="margin-top: 30mm; text-align: right;">
  <div style="border-top: 1px solid #000; padding-top: 5mm; width: 60mm; margin-left: auto;">
    Authorized Signatory
  </div>
</div>
```

### 7c. Watermark — let the dialog handle it

Don't bake watermarks into the template. Set `Watermark Mode = Document Status` (auto-resolves to DRAFT/SUBMITTED/CANCELLED) or `Custom Text` in **Scan Me Settings**, then optionally override per-print in the dialog. The engine overlays a rotated, semi-transparent watermark behind your content.

### 7d. Verified QR in the footer

```html
<div id="footer-html" style="font-size: 9pt;">
  <table style="width: 100%;">
    <tr>
      <td>{{ doc.name }} | Generated {{ frappe.utils.now_datetime().strftime('%d %b %Y, %I:%M %p') }}</td>
      <td style="text-align: right;">
        {{ verify_qr_img(doc.doctype, doc.name, size="18mm") }}
      </td>
    </tr>
  </table>
</div>
```

Unsigned docs render the cell empty. After signing, the verify-page QR appears in every page footer.

---

## 8. Iteration workflow

1. Edit the Print Format in the desk.
2. Open the document → **Advanced Print** icon.
3. Live preview re-renders on every setting change (~500 ms debounce).
4. Tweak template → save → live preview auto-refreshes.

For multi-page testing, set **Copies = 3** and **Footer = All pages** in the dialog so you can verify page-break behavior across many pages without needing different data.

---

## 9. Pitfalls to avoid

| Pitfall | Why it bites | Fix |
|---|---|---|
| `<span class="pageNumber">` in the **body** | Chromium only substitutes `pageNumber` / `totalPages` / `date` / `title` / `url` inside its header/footer template — never in body content | Move them inside `id="footer-html"` (or Letter Head footer) |
| Inline `style="page-break-after: always"` on a heading | Conflicts with the base `page-break-after: avoid` on h1-h6 | Use `class="page-break"` on a sibling `<div>` instead |
| Using `<img>` from external URL | Playwright can't fetch arbitrary URLs at render time | Reference local files (`/files/...`) — engine base64-embeds them |
| `position: fixed` for repeating elements | Chromium PDF prints fixed elements once, not repeated | Use `id="header-html"` / `id="footer-html"` instead |
| Setting page size with `@page` rule | Chromium uses dialog-set page size (A4 default) | Don't override — let the dialog decide |
| Adding `<script>` for client-side rendering | Scan Me waits for `load` only; no JS run window | Render server-side via Jinja |
| Putting layout in tables with thousands of rows | Each row gets `break-inside: avoid` — Chrome falls back when row > page | Pre-paginate in Jinja or split into chunks |
| Mixing Frappe core's `.page-break` class with content inside | Frappe core also ships this class; behavior matches ours | Safe — but be aware they're equivalent |

---

## 10. Quick reference card

```html
<!-- Force next-page start -->
<div class="page-break"></div>

<!-- This element starts a new page -->
<h2 class="new-page">Annexure A</h2>

<!-- Keep block together -->
<div class="no-split">…</div>

<!-- Hide from PDF -->
<div class="no-print">…</div>

<!-- Long unbreakable string -->
<td class="breakable">{{ very_long_id }}</td>

<!-- Body header & footer (auto-promoted to page margins) -->
<div id="header-html">…</div>
<div id="footer-html">…</div>

<!-- Page numbers -->
<span class="pageNumber"></span> / <span class="totalPages"></span>

<!-- Jinja helpers -->
{{ qr_img("text", size="30mm") }}
{{ verify_qr_img(doc.doctype, doc.name) }}
```

---

## 11. When to ask for help

- Layout drift between Advanced Print and Standard Print → expected; design for Advanced
- Row not splitting cleanly → check if row content fits in a page; if not, split the data
- Watermark not showing → check `Watermark Mode` in Scan Me Settings is not `Disabled`
- QR not appearing → confirm doc is signed (`generate_verified_qr` ran) for `verify_qr_img`
- Logo missing → confirm file exists at `/files/...` or `/assets/...`, paths case-sensitive

Open an issue at https://github.com/Tusharp21/scan_me/issues with the print format JSON + the document JSON if behavior surprises you.
