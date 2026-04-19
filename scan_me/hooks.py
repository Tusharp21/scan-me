app_name = "scan_me"
app_title = "Scan Me"
app_publisher = "Tushar Patel"
app_description = "QR and Barcode Scanner"
app_email = "ptusharwrk139@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "scan_me",
# 		"logo": "/assets/scan_me/logo.png",
# 		"title": "Scan Me",
# 		"route": "/scan_me",
# 		"has_permission": "scan_me.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/scan_me/css/scan_me.css"
app_include_js = [
	"assets/scan_me/js/qrcode.min.js",
	"/assets/scan_me/js/generate_qr.js",
	"/assets/scan_me/js/hardcopy_button.js",
]

# include js, css files in header of web template
# web_include_css = "/assets/scan_me/css/scan_me.css"
# web_include_js = "/assets/scan_me/js/scan_me.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "scan_me/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "scan_me/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "scan_me.utils.jinja_methods",
# 	"filters": "scan_me.utils.jinja_filters"
# }

fixtures = [
	{
		"doctype": "Letter Head",
		"filters": [["name", "in", ["Letter Head By Scan Me"]]],
	},
]

jinja = {
	"methods": [
		"scan_me.utils.jinja_functions.qr",
		"scan_me.utils.jinja_functions.barcode",
		"scan_me.utils.jinja_functions.qr_link",
		"scan_me.utils.jinja_functions.qr_img",
		"scan_me.utils.jinja_functions.qr_link_img",
		"scan_me.utils.jinja_functions.verify_qr",
		"scan_me.utils.jinja_functions.verify_qr_img",
	],
}
# Installation
# ------------

# before_install = "scan_me.install.before_install"
# after_install = "scan_me.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "scan_me.uninstall.before_uninstall"
# after_uninstall = "scan_me.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "scan_me.utils.before_app_install"
# after_app_install = "scan_me.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "scan_me.utils.before_app_uninstall"
# after_app_uninstall = "scan_me.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "scan_me.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"scan_me.tasks.all"
# 	],
# 	"daily": [
# 		"scan_me.tasks.daily"
# 	],
# 	"hourly": [
# 		"scan_me.tasks.hourly"
# 	],
# 	"weekly": [
# 		"scan_me.tasks.weekly"
# 	],
# 	"monthly": [
# 		"scan_me.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "scan_me.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "scan_me.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "scan_me.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["scan_me.utils.before_request"]
# after_request = ["scan_me.utils.after_request"]

# Job Events
# ----------
# before_job = ["scan_me.utils.before_job"]
# after_job = ["scan_me.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"scan_me.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
