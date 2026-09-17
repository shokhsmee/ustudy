{
    "name": "Ustudy Jadval (operatsion maydon)",
    "version": "19.0.1.0.0",
    "author": "Ustudy",
    "summary": "Akademiya jadvali: kun/hafta/xona ko'rinishlari, jonli holat va konfliktlar",
    "description": """
Alohida root app: dars jadvalining operatsion ko'rinishi.

Mavjud "Jadval doskasi" (ustudy_dars_jadvali) va "Dars jadvali"/"Xonalar
bandligi" ekranlariga tegilmaydi — bu qo'shimcha, asosiy jadval maydoni.
Ma'lumot manbai ham, dars qo'shish/band qilish sehrgarlari ham o'sha
modullardan olinadi, shuning uchun barcha funksiyalar o'zgarishsiz qoladi.
""",
    "depends": [
        # bookings (dars.jadvali.booking), the add-lesson/booking wizards and
        # the free-window helpers all live there: this app reuses them as-is
        # instead of duplicating the schedule logic.
        "ustudy_dars_jadvali",
    ],
    "data": [
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ustudy_jadval/static/src/workspace/workspace.scss",
            "ustudy_jadval/static/src/workspace/workspace.esm.js",
            "ustudy_jadval/static/src/workspace/workspace.xml",
        ],
    },
    "application": True,
    "installable": True,
    "license": "LGPL-3",
}
