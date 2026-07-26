# -*- coding: utf-8 -*-
{
    'name': "Ustoz Oyligi (Teacher Salary)",
    'version': '19.0.1.7.1',
    'summary': "Ustozlar oyligini davomat asosida hisoblash",
    'description': """
Ustoz oyligi hisoblanishi
=========================
Ustoz har bir darsga davomat qiladi. Davomat tasdiqlanganda, o'sha darsda
aktiv (davomat qilgan) o'quvchilar soni ustozning toifasiga belgilangan
"1 o'quvchi uchun summa" ga ko'paytiriladi va bu ustoz balansiga tranzaksiya
sifatida yoziladi.

Har bir tranzaksiya o'zgarmas (immutable) surat (snapshot) hisoblanadi:
o'sha darsdagi guruh, dars raqami, moduli, ustoz, o'quvchilar ro'yxati va
summa saqlanadi. Keyinchalik o'quvchi kursni tark etsa ham o'tgan darsning
summasi o'zgarmaydi.

Toifalar (A/B) va darajalar (A1..A3, B1..B3) — foizlar va summalar bilan —
Moliya ilovasidagi Sozlamalar menyusidan to'liq tahrirlanadi.
    """,
    'author': 'Custom',
    'license': 'LGPL-3',
    'category': 'Human Resources',
    'application': True,
    'installable': True,
    'depends': [
        'base',
        'mail',
        'hr',
        'ustudy_group',
        'edu_finance',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'data/salary_default_data.xml',
        'views/salary_config_views.xml',
        'views/salary_line_views.xml',
        'views/salary_payment_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/hr_employee_views.xml',
        'views/edu_timetable_views.xml',
        'views/menu_views.xml',
    ],
}
