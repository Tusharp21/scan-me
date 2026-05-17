# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ScanMeDoctype(Document):
	# Row-level invariants live on the parent ScanMeSettings.validate() —
	# Frappe doesn't call a child's controller validate() during parent save.
	pass
