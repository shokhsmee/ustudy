{
    "name": "Ustudy Groups",
    "version": "1.11.0",
    "author": "Ustudy",
    "depends": [
        "ustudy_student",
        "website_slides",
        "mail",
        "hr",
        "project",
        # Administrator role (admin_security.xml): open-lesson leads live in
        # CRM, team-building history in Events — installing/upgrading this
        # module installs both apps.
        "crm",
        "event",
        # 'edu_finance',
    ],
    "data": [
        "security/teacher_security.xml",
        "security/admin_security.xml",
        "security/ir.model.access.csv",
        "views/menu_root.xml",
        "data/edu_rooms.xml",
        # edu_timetable_views must load before edu_attendance_views: the
        # attendance file inherits view_edu_timetable_form (fresh installs
        # broke on the old order; upgrades never noticed because the xmlid
        # already existed).
        "views/edu_timetable_views.xml",
        "views/edu_attendance_views.xml",
        "views/week_days.xml",
        "views/edu_group_views.xml",
        "views/student_views.xml",
        "views/slide_slide_views.xml",
        "views/edu_config_views.xml",
        "views/edu_modul_views.xml",
        # 'views/cc_finance_student_payment_views.xml',
        "views/menu.xml",
        "views/camera_wizard_views.xml",
        'views/camera_end_wizard_views.xml',
        "views/res_partner_groups_button.xml",
        "views/add_student_wizard_views.xml",
    ],
    'assets': {
        'web.assets_backend': [
            'ustudy_group/static/src/js/camera_wizard.js',
            "ustudy_group/static/src/js/group_dashboard.js",
            "ustudy_group/static/src/scss/group_dashboard.scss",
            "ustudy_group/static/src/davomat_matrix/davomat_matrix.scss",
            "ustudy_group/static/src/davomat_matrix/davomat_matrix.esm.js",
            "ustudy_group/static/src/davomat_matrix/davomat_matrix.xml",
            "ustudy_group/static/src/room_bandlik/room_bandlik.scss",
            "ustudy_group/static/src/room_bandlik/room_bandlik_arch_parser.esm.js",
            "ustudy_group/static/src/room_bandlik/room_bandlik_model.esm.js",
            "ustudy_group/static/src/room_bandlik/room_bandlik_renderer.esm.js",
            "ustudy_group/static/src/room_bandlik/room_bandlik_controller.esm.js",
            "ustudy_group/static/src/room_bandlik/room_bandlik_view.esm.js",
            "ustudy_group/static/src/room_bandlik/room_bandlik_renderer.xml",
            "ustudy_group/static/src/room_bandlik/room_bandlik_controller.xml",
        ],
    },
    "application": True,
}