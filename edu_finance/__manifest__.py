# -*- coding: utf-8 -*-
{
    'name': 'Education Finance Management',
    'version': '19.0.1.3.1',
    'category': 'Accounting',
    'summary': 'Manage income and expenses for education center',
    'author' : 'Shohjahon Obruyev',
    'description': """
        Education Finance Management
        =============================
        * Track income and expenses
        * Manage payment methods and types
        * Update student and employee balances automatically
        * Support for teacher payments
    """,
    'depends': ['base', 'hr', 'contacts',"ustudy_group"],
    'data': [
        'security/finance_security.xml',
        'security/ir.model.access.csv',
        'security/ir_rule.xml',
        'data/sequence_data.xml',
        'data/payment_method_data.xml',
        'data/payment_type_data.xml',
        'views/cc_finance_views.xml',
        'views/payment_method_views.xml',
        'views/payment_type_views.xml',
        'views/res_partner_views.xml',
        # "views/edu_payment_wizard_views.xml",
        'views/hr_employee_views.xml',
        'views/menu_views.xml',
        
        "views/portal_templates.xml",
        "views/portal_my_finance.xml",
    ],
    'assets': {
        'web.assets_backend': [
            "edu_finance/static/src/js/finance_dashboard.js",
        ],
    },
    'image':"cc_finance,static/description/icon.png",
    'installable': True,
    'application': True,
    'auto_install': False,
}