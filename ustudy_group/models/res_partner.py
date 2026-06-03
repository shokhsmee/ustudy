from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    group_student_ids = fields.One2many(
        "edu.group.student",
        "student_id",
        string="Groups",
    )

    group_count = fields.Integer(
        string="Groups",
        compute="_compute_group_count",
        store=False,
    )

    def _compute_group_count(self):
        for partner in self:
            partner.group_count = len(partner.group_student_ids)

    def action_view_groups(self):
        """Smart button: open groups that contain this student."""
        self.ensure_one()
        action = self.env.ref("ustudy_group.action_edu_group_list").read()[0]
        # only groups where this partner is in student_line_ids
        action["domain"] = [("student_line_ids.student_id", "=", self.id)]
        action["context"] = dict(self.env.context or {}, default_student_id=self.id)
        return action

    # ----------------------------------------------------------------
    # Aggregate fields for the Talabalar list view.
    # A student in multiple groups still shows as a single row; the
    # values aggregate across their non-cancelled enrollments so the
    # "O'quvchilar" layout (module / passed / amount / davomati) works
    # at the partner level.
    # ----------------------------------------------------------------
    current_module_summary = fields.Char(
        string="Joriy modul",
        compute="_compute_aggregate_group_info",
        store=False,
    )

    passed_lessons_total = fields.Integer(
        string="O'tilingan darslar",
        compute="_compute_aggregate_group_info",
        store=False,
    )

    passed_lessons_amount_total = fields.Float(
        string="O'tilgan darslar summasi",
        compute="_compute_aggregate_group_info",
        store=False,
    )

    student_status_summary = fields.Char(
        string="Status",
        compute="_compute_aggregate_group_info",
        store=False,
    )

    davomat_summary = fields.Char(
        string="Davomati",
        compute="_compute_aggregate_group_info",
        store=False,
    )

    student_balance = fields.Float(
        string="O'quvchi balans",
        compute="_compute_student_balance",
        store=False,
        readonly=True,
        help="Mirrors res.partner.finance_balance (defined in edu_finance, "
             "which depends on ustudy_group — we can't reference it in views "
             "loaded before edu_finance, so we expose it through a safe "
             "computed field here).",
    )

    def _compute_student_balance(self):
        has_field = "finance_balance" in self.env["res.partner"]._fields
        for partner in self:
            partner.student_balance = partner.finance_balance if has_field else 0.0

    @api.depends(
        "group_student_ids",
        "group_student_ids.state",
        "group_student_ids.current_module_id",
        "group_student_ids.passed_lessons_count",
        "group_student_ids.passed_lessons_amount",
        "group_student_ids.attended_lessons_count",
    )
    def _compute_aggregate_group_info(self):
        for partner in self:
            # All non-cancelled enrollments — these "represent" the student.
            lines = partner.group_student_ids.filtered(
                lambda l: l.state != "cancelled"
            )

            active = lines.filtered(lambda l: l.state == "active")

            # Joriy modul: unique active module names joined with comma.
            modules = active.mapped("current_module_id.name")
            partner.current_module_summary = ", ".join(sorted(set(filter(None, modules)))) or ""

            # Lesson aggregates: sum across active enrollments.
            partner.passed_lessons_total = sum(active.mapped("passed_lessons_count"))
            partner.passed_lessons_amount_total = sum(active.mapped("passed_lessons_amount"))

            # Davomati: total attended / total passed across active enrollments.
            attended_sum = sum(active.mapped("attended_lessons_count"))
            passed_sum = partner.passed_lessons_total
            partner.davomat_summary = f"{attended_sum}/{passed_sum}"

            # Status:
            #  - "Faol (N)" if any line is active (N = active count)
            #  - else "Muzlatilgan" if any frozen
            #  - else "Tugatgan" if any completed
            #  - else empty
            if active:
                partner.student_status_summary = f"Faol ({len(active)})"
            elif lines.filtered(lambda l: l.state == "frozen"):
                partner.student_status_summary = "Muzlatilgan"
            elif lines.filtered(lambda l: l.state == "completed"):
                partner.student_status_summary = "Tugatgan"
            else:
                partner.student_status_summary = ""
