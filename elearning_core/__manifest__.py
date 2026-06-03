{
    "name": "eLearning Core",
    "version": "19.0.1.0.0",
    "summary": "eLearning sozlamalari: ortiqcha bo'limlarni yashirish va barcha darslarni nashr qilish",
    "description": """
eLearning Core
==============
- Slide formasida 'Qo'shimcha manbalar' va 'Viktorina' yorliqlarini yashiradi.
- Kurs (channel) formasida 'Barcha darslarni nashr qilish' tugmasini qo'shadi.
- O'zbek tilidagi tarjimalar bilan birga keladi.
""",
    "category": "Website/eLearning",
    "author": "Tour",
    "license": "LGPL-3",
    "depends": ["website_slides"],
    "data": [
        "views/slide_slide_views.xml",
        "views/slide_channel_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
