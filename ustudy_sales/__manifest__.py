# -*- coding: utf-8 -*-
{
    'name': 'UStudy Sotuvlar',
    'version': '19.0.1.1.0',
    'category': 'Sales',
    'summary': "Kurs sotuvlari: buyurtmalar, chegirma, edu_finance to'lovlari bilan integratsiya",
    'description': """
Sotuv bo'limi uchun soddalashtirilgan buyurtmalar ilovasi.

Buyurtma (edu.sale.order) sale.order tuzilishida, lekin account/sale
modullarisiz ishlaydi (Invoicing ilovasi o'rnatilmaydi). Kurslar mahsulot
(product.template) sifatida tanlanadi, qator darajasida chegirma bor.

"Hisob-faktura yaratish" tugmasi cc.finance (edu_finance) da qoralama kirim
yozuvini yaratadi, kassa uni To'lovlar ilovasida tasdiqlaydi. Buyurtmada
smart button orqali bog'langan yozuvlar, hamda To'langan / Tasdiqlanishi
kutilyotgan / Qarzdorlik / Ortiqcha to'langan bloki ko'rinadi.

"Sotuv menejeri" roli (guruh + res.users.role) bilan birga keladi.
""",
    'author': 'Ustudy',
    'license': 'LGPL-3',
    'depends': [
        'edu_finance',
        'product',
        'ustudy_group',
        'base_user_role',
        'amocrm_connector',
    ],
    'data': [
        'security/sales_security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/payment_type_data.xml',
        'data/role_data.xml',
        'views/sale_order_views.xml',
        'views/invoice_wizard_views.xml',
        'views/cc_finance_views.xml',
        'views/menu_views.xml',
        'views/sales_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ustudy_sales/static/src/sales_kpi/sales_kpi.esm.js',
            'ustudy_sales/static/src/sales_kpi/sales_kpi.xml',
        ],
    },
    'application': True,
    'installable': True,
}
