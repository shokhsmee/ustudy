# -*- coding: utf-8 -*-
{
    'name': 'Education Finance Management',
    'version': '19.0.2.0.0',
    'category': 'Accounting',
    'summary': 'Education finance engine backed by standard Odoo accounting (account.move)',
    'author': 'Shohjahon Obruyev',
    'description': """
Education Finance Management — Block B: Financial Core
=======================================================
* Standardized ledger: all money flows through account.move (out_invoice / in_invoice)
* Refund workflow with approval state machine → Odoo credit notes (out_refund)
* Abstract payment gateway adapter pattern (Payme, Click, Uzum — plug-and-play)
* Soft-lock on validated ledger entries (overridable by Finance Ledger Admin)
* finance_balance derived from the ledger (no more manual +=/−= mutation)
* Full audit trail via chatter + accounting journal entries
    """,
    'depends': [
        'base',
        'mail',
        'hr',
        'contacts',
        'account',
        'ustudy_group',
    ],
    'data': [
        # Security (groups must load before ACLs)
        'security/finance_groups.xml',
        'security/ir.model.access.csv',
        # 'security/ir_rule.xml',

        # Data
        'data/sequence_data.xml',
        'data/payment_method_data.xml',
        'data/payment_type_data.xml',

        # Views
        'views/cc_finance_views.xml',
        'views/cc_finance_refund_views.xml',
        'views/payment_gateway_views.xml',
        'views/edu_config_accounting_views.xml',
        'views/payment_method_views.xml',
        'views/payment_type_views.xml',
        'views/res_partner_views.xml',
        'views/hr_employee_views.xml',
        'views/menu_views.xml',
        'views/portal_templates.xml',
        'views/portal_my_finance.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'edu_finance/static/src/js/finance_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
