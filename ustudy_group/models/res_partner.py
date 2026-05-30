from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # A student is a res.partner (is_student=True). Enrollment is the
    # many-to-many junction 'edu.group.student', so a single student can be
    # a member of any number of groups at the same time.
    group_student_ids = fields.One2many(
        "edu.group.student",
        "student_id",
        string="Groups",
    )

    # Convenience flat list of the groups this student belongs to.
    enrolled_group_ids = fields.Many2many(
        "edu.group",
        string="Enrolled Groups",
        compute="_compute_enrolled_groups",
        store=False,
    )

    group_count = fields.Integer(
        string="Groups",
        compute="_compute_group_count",
        store=False,
    )
    active_group_count = fields.Integer(
        string="Active Groups",
        compute="_compute_group_count",
        store=False,
    )

    @api.depends("group_student_ids")
    def _compute_enrolled_groups(self):
        for partner in self:
            partner.enrolled_group_ids = partner.group_student_ids.mapped("group_id")

    @api.depends("group_student_ids", "group_student_ids.state")
    def _compute_group_count(self):
        for partner in self:
            lines = partner.group_student_ids
            partner.group_count = len(lines)
            partner.active_group_count = len(
                lines.filtered(lambda l: l.state == "active")
            )

    def action_view_groups(self):
        """Smart button: open groups that contain this student."""
        self.ensure_one()
        action = self.env.ref("ustudy_group.action_edu_group_list").read()[0]
        # only groups where this partner is in student_line_ids
        action["domain"] = [("student_line_ids.student_id", "=", self.id)]
        action["context"] = dict(self.env.context or {}, default_student_id=self.id)
        return action
