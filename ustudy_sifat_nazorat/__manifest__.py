# -*- coding: utf-8 -*-
{
    "name": "Sifat Nazorat",
    "version": "19.0.1.6.0",
    "summary": "Kelmagan o'quvchilar nazorati — sababli/sababsiz tasnifi",
    "description": """
Sifat Nazorat
=============
Davomatda "Yo'q" (kelmadi) deb belgilangan har bir o'quvchi uchun alohida
nazorat yozuvi yaratiladi. Yozuvda sabab tasnifi (Sababli / Sababsiz),
tavsif va chatter bor.

- Davomat satrida Yo'q tanlansa, sabab tanlash wizard'i ochiladigan tugma
  chiqadi (davomat formasi va davomat matritsasida).
- Sababli deb belgilangan katak davomat matritsasida yashil hoshiya va
  meditsina (+) belgisi bilan ko'rsatiladi.
- Sifat Nazorat ilovasida yozuvlar kun bo'yicha, ichida guruh bo'yicha
  guruhlangan ro'yxatda chiqadi; ro'yxat ustida mini dashboard (jami /
  sababli / sababsiz / belgilanmagan) ko'rsatiladi.
    """,
    "author": "Shohjahon Obruyev",
    "license": "LGPL-3",
    "category": "Education",
    "application": True,
    "installable": True,
    "depends": [
        "mail",
        "ustudy_group",
        # Call-history lookup behind the "Qo'ng'iroqlar" smart button. Read-only:
        # calls are matched by phone number, never linked to nazorat records.
        "onlinepbx_calls",
    ],
    "data": [
        "security/sifat_nazorat_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/absence_reason_data.xml",
        "views/sifat_nazorat_views.xml",
        "views/absence_reason_views.xml",
        "views/absence_reason_wizard_views.xml",
        "views/edu_attendance_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ustudy_sifat_nazorat/static/src/davomat_matrix_sn.scss",
            "ustudy_sifat_nazorat/static/src/davomat_matrix_sn.esm.js",
            "ustudy_sifat_nazorat/static/src/davomat_matrix_sn.xml",
            "ustudy_sifat_nazorat/static/src/sifat_nazorat_dashboard.js",
        ],
    },
    "post_init_hook": "post_init_backfill",
}
