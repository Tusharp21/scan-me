# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Chrome-PDF pipeline. Re-exports generate_chrome_pdf so the JS endpoint path is stable."""

from .generator import generate_chrome_pdf

__all__ = ["generate_chrome_pdf"]
