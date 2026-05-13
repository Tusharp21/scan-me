# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Attach the rendered PDF to the source document as a private File record."""

import frappe


def _attach_pdf_to_doc(pdf_bytes, safe_name, doctype, name):
	"""Save the rendered PDF as a File record attached to the source document.

	Uses Frappe's ``save_file`` helper which correctly handles content
	persistence (writes to disk, hashes, etc.). Permission check is explicit so
	we can log the refusal. Failures are logged, not raised — the user still
	gets their download.
	"""
	if not frappe.has_permission(doctype, "write", name):
		frappe.log_error(
			"Scan Me: attach PDF denied",
			f"User {frappe.session.user} tried to attach PDF without write access to {doctype} {name}",
		)
		return

	try:
		from frappe.utils.file_manager import save_file

		save_file(
			fname=f"{safe_name}.pdf",
			content=pdf_bytes,
			dt=doctype,
			dn=name,
			is_private=1,
		)
		frappe.db.commit()  # ensure the File row persists even with response streaming
	except Exception:
		frappe.log_error("Scan Me: attach PDF failed", frappe.get_traceback())
