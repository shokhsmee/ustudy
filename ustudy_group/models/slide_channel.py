from odoo import fields, models


class SlideChannel(models.Model):
    _inherit = "slide.channel"

    # Inverse of edu.group.slide_channel_id (stored related to the course's
    # channel). Exists so record rules can scope eLearning courses to the
    # groups a teacher owns — see rule_slide_channel_teacher_scope in
    # security/teacher_security.xml.
    edu_group_ids = fields.One2many(
        "edu.group",
        "slide_channel_id",
        string="O'quv guruhlari",
    )
