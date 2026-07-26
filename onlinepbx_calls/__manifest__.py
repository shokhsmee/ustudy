{
    "name": "OnlinePBX Call History",
    "summary": "Receive call history from OnlinePBX via webhook",
    "version": "19.0.1.2.0",
    "category": "Tools",
    "author": "Shohjahon Obruyev",
    "depends": ["base", "contacts","hr"],
    "data": [
        "security/ir.model.access.csv",
        "data/onlinepbx_demo_categories.xml",
        # actions & views FIRST
        "views/onlinepbx_call_views.xml",
        "views/onlinepbx_settings_views.xml",
        "views/onlinepbx_employee_stats_views.xml",
        # menus LAST (they reference actions above)
        "views/onlinepbx_menus.xml",
        "views/hr_employee_views.xml",
    ],
    "installable": True,
    "application": True,
}
