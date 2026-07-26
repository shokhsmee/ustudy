# -*- coding: utf-8 -*-
{
    'name': "UStudy Coin Tizimi",
    'version': '19.0.1.2.0',
    'summary': "O'quvchi kartochkasida vazifalardan olingan XP ni coin ko'rinishida ko'rsatish",
    'description': """
Coin tizimi
===========
Har bir o'quvchining kartochkasida (kontakt formasida) alohida "Coin tizimi"
bo'limi: qaysi vazifadan (uy vazifasi) qancha coin (XP) olingani animatsiyali
jadval ko'rinishida ko'rsatiladi.

Coin manbasi — uy vazifasi bahosi (edu.homework.submission): vazifa
topshirilganda XP beriladi (xp_amount), shu XP coin sifatida ko'rsatiladi.
    """,
    'author': 'Custom',
    'license': 'LGPL-3',
    'category': 'Education',
    'application': False,
    'installable': True,
    'depends': [
        'ustudy_student',
        'ustudy_homework',
    ],
    'data': [
        'views/res_partner_coin_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ustudy_coin/static/src/coin_table/coin_table.scss',
            'ustudy_coin/static/src/coin_table/coin_table.esm.js',
            'ustudy_coin/static/src/coin_table/coin_table.xml',
        ],
    },
}
