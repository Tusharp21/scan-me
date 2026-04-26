# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ScanMeDoctype(Document):
	"""Child-table row of Scan Me Settings — one row per signable doctype."""

	def validate(self):
		# Frappe's Link-field validation already rejects a non-existent
		# doctype, so we only add the checks it doesn't cover: signing a
		# Single has no ``ref_docname`` to attach the Verified QR to, and
		# signing a child table means "sign one grid row" which the Verified
		# QR schema (ref_doctype + ref_docname) can't represent. Both would
		# blow up later in generate_verified_qr; catching it here gives the
		# admin a clear message at config time instead of a traceback at
		# sign time.
		if not self.ref_doctype:
			return
		meta = frappe.get_meta(self.ref_doctype)
		if getattr(meta, "issingle", 0):
			frappe.throw(
				frappe._(
					"'{0}' is a Single doctype and can't be signed — pick a doctype with individual records."
				).format(self.ref_doctype)
			)
		if getattr(meta, "istable", 0):
			frappe.throw(
				frappe._(
					"'{0}' is a child table and can't be signed on its own — pick the parent doctype instead."
				).format(self.ref_doctype)
			)
