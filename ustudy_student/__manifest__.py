{
    "name": "Ustudy Students",
    "version": "1.0.2",
    "author": "Ustudy",
    "depends": [
        "contacts",        # res.partner
        "website_slides",  # eLearning
    ],
    "data": [
        "security/student_groups.xml",
        "wizards/student_password_wizard_view.xml",
        "security/ir.model.access.csv",

        "views/student_partner_list_kanban.xml",     # 1) tree + kanban
        "views/student_partner_form.xml",      # 2) form inherit
        "views/student_menu.xml",              # 3) action/menu (ref ishlatadi)
        "views/cc_region_views.xml",
    ],
    'assets': {
        'web.assets_backend': [
            'ustudy_student/static/src/css/custom.css',
        ],
    },
    "application": True,
    "post_init_hook": "post_init_hook",
}