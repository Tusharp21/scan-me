# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ScanMeDoctype(Document):
	"""Child-table row of Scan Me Settings — one row per signable doctype.

	Row-level invariants (no Singles, no child tables) live on the parent
	``ScanMeSettings.validate()`` because Frappe doesn't call a child's
	controller ``validate()`` during the parent save flow.
	"""

	pass
