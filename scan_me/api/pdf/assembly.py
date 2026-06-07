# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Multi-copy assembly + per-page header/footer mode rendering."""

from io import BytesIO

from pypdf import PdfReader, PdfWriter

from .letterhead import _build_footer_template, _build_header_template


def _merge_pdfs(pdf_bytes_list):
	"""Concatenate PDF byte blobs into a single PDF."""
	writer = PdfWriter()
	for pdf_bytes in pdf_bytes_list:
		reader = PdfReader(BytesIO(pdf_bytes))
		for page in reader.pages:
			writer.add_page(page)
	out = BytesIO()
	writer.write(out)
	return out.getvalue()


def _pages_with_status(total, mode):
	"""1-indexed page numbers where header/footer should appear."""
	if total <= 0:
		return set()
	if mode == "All pages":
		return set(range(1, total + 1))
	if mode == "First page only":
		return {1}
	if mode == "Last page only":
		return {total}
	if mode == "First and last pages":
		return {1, total}
	return set()  # "None"


def _group_pages_by_status(total, header_on, footer_on):
	"""Yield (start, end, has_header, has_footer) for each consecutive same-status run."""
	current_status = None
	run_start = None
	run_end = None
	for p in range(1, total + 1):
		status = (p in header_on, p in footer_on)
		if current_status is None:
			current_status = status
			run_start = p
			run_end = p
		elif status == current_status:
			run_end = p
		else:
			yield run_start, run_end, current_status[0], current_status[1]
			current_status = status
			run_start = p
			run_end = p
	if current_status is not None:
		yield run_start, run_end, current_status[0], current_status[1]


def _render_copy_with_modes(
	page, label, header_content, footer_content, margins, header_mode, footer_mode, landscape=False
):
	"""Render one copy honouring header_mode/footer_mode. Margins stay constant across
	per-group renders so page breaks don't shift. ``landscape`` rotates the A4 page."""
	full_header = _build_header_template(header_content, label)
	full_footer = _build_footer_template(footer_content)
	empty_tpl = "<div></div>"

	if header_mode == "All pages" and footer_mode == "All pages":
		return page.pdf(
			format="A4",
			landscape=landscape,
			display_header_footer=True,
			header_template=full_header,
			footer_template=full_footer,
			print_background=True,
			margin=margins,
		)

	if header_mode == "None" and footer_mode == "None":
		return page.pdf(
			format="A4",
			landscape=landscape,
			display_header_footer=True,
			header_template=empty_tpl,
			footer_template=empty_tpl,
			print_background=True,
			margin=margins,
		)

	# Reference render with full H/F to learn page count.
	reference = page.pdf(
		format="A4",
		landscape=landscape,
		display_header_footer=True,
		header_template=full_header,
		footer_template=full_footer,
		print_background=True,
		margin=margins,
	)
	total = len(PdfReader(BytesIO(reference)).pages)
	header_on = _pages_with_status(total, header_mode)
	footer_on = _pages_with_status(total, footer_mode)

	groups = list(_group_pages_by_status(total, header_on, footer_on))

	# Reference already matches desired layout — return as-is.
	if len(groups) == 1 and groups[0][2] and groups[0][3]:
		return reference

	writer = PdfWriter()
	for start, end, has_header, has_footer in groups:
		hdr = full_header if has_header else empty_tpl
		ftr = full_footer if has_footer else empty_tpl
		segment = page.pdf(
			format="A4",
			landscape=landscape,
			display_header_footer=True,
			header_template=hdr,
			footer_template=ftr,
			print_background=True,
			margin=margins,
			page_ranges=f"{start}-{end}",
		)
		for p in PdfReader(BytesIO(segment)).pages:
			writer.add_page(p)
	out = BytesIO()
	writer.write(out)
	return out.getvalue()
