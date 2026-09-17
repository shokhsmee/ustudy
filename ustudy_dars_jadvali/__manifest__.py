{
    "name": "Ustudy Dars Jadvali (Doska)",
    "version": "1.9.1",
    "author": "Ustudy",
    "summary": "Excel-style room/time schedule board with Reja/Fakt totals",
    "depends": [
        "ustudy_group",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/lesson_wizard_views.xml",
        "views/booking_views.xml",
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ustudy_dars_jadvali/static/src/board/board.scss",
            "ustudy_dars_jadvali/static/src/board/board.esm.js",
            "ustudy_dars_jadvali/static/src/board/board.xml",
            "ustudy_dars_jadvali/static/src/room_bandlik_patch/room_bandlik_patch.scss",
            "ustudy_dars_jadvali/static/src/room_bandlik_patch/room_bandlik_patch.esm.js",
        ],
    },
    "application": False,
    "license": "LGPL-3",
}
