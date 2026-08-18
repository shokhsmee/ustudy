# -*- coding: utf-8 -*-
{
    "name": "amoCRM Connector",
    "version": "19.0.1.3.0",
    "summary": "amoCRM integratsiyasi — xodimlarni sinxronlash (long-lived token)",
    "description": """
amoCRM Connector
================
amoCRM bilan integratsiya. Sozlamalar > amoCRM bo'limida ulanish ma'lumotlari
(Base URL + uzoq muddatli Access Token) kiritiladi.

Birinchi bosqich: amoCRM xodimlarini (foydalanuvchilarini) Odoo ga sinxronlash
va har bir amoCRM xodimini Odoo foydalanuvchisiga bog'lash (mapping).
    """,
    "author": "Custom",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "application": False,
    "installable": True,
    "depends": ["base"],
    "data": [
        "security/amocrm_security.xml",
        "security/ir.model.access.csv",
        "views/amocrm_employee_views.xml",
        "views/amocrm_dashboard_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "amocrm_connector/static/src/kpi_dashboard/kpi_dashboard.scss",
            "amocrm_connector/static/src/kpi_dashboard/kpi_dashboard.esm.js",
            "amocrm_connector/static/src/kpi_dashboard/kpi_dashboard.xml",
        ],
    },
}
