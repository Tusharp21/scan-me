# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Parsing helpers for the JSON ``options`` blob from the Advanced Print page."""

import json

MAX_COPIES = 5

# Options schema sent by scan_me_print.js (see DEFAULT_OPTIONS for keys/types).
DEFAULT_OPTIONS = {
	"copy_count": 1,
	"copy_labels": "",
	"orientation": "Portrait",
	"header_mode": "All pages",
	"footer_mode": "All pages",
	"include_qr": 0,
	"qr_position": "Top Right",
	"qr_source": "Verified QR Link",
	"qr_custom_text": "",
	"qr_force_insert": 0,
	"append_signature": 0,
	"apply_pades": 0,
	"watermark_text": "",
	"attach_to_doc": 0,
}


def _parse_options(raw):
	if not raw:
		return dict(DEFAULT_OPTIONS)
	if isinstance(raw, dict):
		parsed = raw
	else:
		try:
			parsed = json.loads(raw)
		except (ValueError, TypeError):
			parsed = {}
	merged = dict(DEFAULT_OPTIONS)
	merged.update({k: v for k, v in parsed.items() if k in DEFAULT_OPTIONS})
	try:
		merged["copy_count"] = max(1, min(int(merged["copy_count"]), MAX_COPIES))
	except (ValueError, TypeError):
		merged["copy_count"] = 1
	return merged


def _parse_copy_labels(raw, count):
	"""Split labels and pad with auto names; empty raw → N copies with no badge."""
	if count <= 1:
		return [""]
	raw = (raw or "").strip()
	if not raw:
		return [""] * count
	labels = [s.strip() for s in raw.split(",") if s.strip()]
	while len(labels) < count:
		labels.append(f"COPY {len(labels) + 1}")
	return labels[:count]
