import os as _os

# Pin Playwright's Chromium cache to a bench-local path so PDF rendering
# survives Playwright pip upgrades and doesn't pollute the user's
# ``~/.cache``. ``setdefault`` is deliberate — operators can override by
# exporting PLAYWRIGHT_BROWSERS_PATH before bench starts. This file runs
# the moment Frappe imports the app on every web/worker process, so by
# the time ``sync_playwright()`` is called the env is already set.
_os.environ.setdefault(
	"PLAYWRIGHT_BROWSERS_PATH",
	_os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "..", "playwright-browsers")),
)

__version__ = "2.1.0"
