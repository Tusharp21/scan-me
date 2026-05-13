# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Letter-Head reads, header/footer template builders, and body-defined
header/footer extraction (id="header-html" / id="footer-html").

Also exposes :func:`_measure_html_height_mm` so the generator can size Chrome's
PDF margin to match the actual rendered height of the header/footer template.
"""

import re

import frappe
from bs4 import BeautifulSoup

from .images import embed_images


def _get_letterhead_raw(letter_head_name):
	"""Read Letter Head from DB and return the raw (image-embedded) content HTML.

	For page numbers, add these in the Letter Head footer HTML:
	  <span class="pageNumber"></span>  — current page
	  <span class="totalPages"></span>  — total pages

	Returns: (header_content_html, footer_content_html, header_h_mm, footer_h_mm)
	"""
	if not letter_head_name:
		return "", "", 0, 0

	if not frappe.db.exists("Letter Head", letter_head_name):
		# Letter Head was deleted or renamed — fall back to no-letterhead render.
		return "", "", 0, 0
	lh = frappe.get_doc("Letter Head", letter_head_name)
	header_content = embed_images(lh.get("content") or "")
	footer_content = embed_images(lh.get("footer") or "")
	header_h = 30 if header_content else 0
	footer_h = 10 if footer_content else 0
	return header_content, footer_content, header_h, footer_h


def _build_header_template(header_content, copy_label=""):
	"""Build Playwright header template HTML, optionally with a copy-label badge."""
	badge = ""
	if copy_label:
		safe_label = frappe.utils.escape_html(copy_label)
		badge = (
			'<div style="padding:2px 10px; border:2px solid #d63030; color:#d63030; '
			"font-weight:bold; font-size:11px; letter-spacing:1.5px; background:white; "
			f'white-space:nowrap;">{safe_label}</div>'
		)

	if not header_content and not badge:
		return "<div></div>"

	return (
		'<div style="width:100%; font-size:12px; padding:2mm 10mm; box-sizing:border-box; '
		'display:flex; justify-content:space-between; align-items:flex-start;">'
		f'<div style="flex:1;">{header_content}</div>'
		f'<div style="flex:0 0 auto; margin-left:10mm;">{badge}</div>'
		"</div>"
	)


def _build_footer_template(footer_content):
	"""Build Playwright footer template HTML."""
	if not footer_content:
		return "<div></div>"
	return (
		'<div style="width:100%; font-size:10px; padding:2mm 10mm; box-sizing:border-box;">'
		f"{footer_content}"
		"</div>"
	)


def extract_body_header_footer(body_html):
	"""Pull elements with id='header-html' / id='footer-html' out of body_html.

	These are commonly kept inside the print body so they remain visible in
	Frappe's HTML print preview; for the actual PDF they should instead become
	the repeating page header/footer (like the Letter Head ones).

	Returns: (header_inner_html, footer_inner_html, cleaned_body_html)
	Either inner value is None when the corresponding id is not present.
	"""
	if not body_html:
		return None, None, body_html
	if "header-html" not in body_html and "footer-html" not in body_html:
		return None, None, body_html

	soup = BeautifulSoup(body_html, "html.parser")

	header_inner = None
	header_el = soup.find(id="header-html")
	if header_el:
		header_inner = header_el.decode_contents()
		header_el.decompose()

	footer_inner = None
	footer_el = soup.find(id="footer-html")
	if footer_el:
		footer_inner = footer_el.decode_contents()
		footer_el.decompose()

	return header_inner, footer_inner, str(soup)


# 96 CSS pixels per inch / 25.4 mm per inch  ≈  3.7795 px per mm
_PX_PER_MM = 96.0 / 25.4


def _measure_html_height_mm(page, html, page_width_mm=210):
	"""Render *html* standalone in *page* and return its rendered height in mm.

	Used to size Chrome's PDF margin.top/bottom to match the actual rendered
	height of header_template/footer_template — Chrome itself does not
	auto-size them, content taller than the reserved margin gets clipped.
	"""
	if not html:
		return 0
	stripped = re.sub(r"\s+", "", html)
	if stripped in ("", "<div></div>"):
		return 0

	width_px = int(page_width_mm * _PX_PER_MM)
	measure_doc = (
		f"<!DOCTYPE html><html><head>"
		f"<style>html,body{{margin:0;padding:0;}}"
		f"#__measure{{width:{width_px}px;}}</style>"
		f'</head><body><div id="__measure">{html}</div></body></html>'
	)
	page.set_content(measure_doc, wait_until="load")
	height_px = page.evaluate("document.getElementById('__measure').offsetHeight") or 0
	return height_px / _PX_PER_MM
