from odoo import models, fields, _


class ResPartner(models.Model):
    _inherit = "res.partner"

    finance_count = fields.Integer(
        string="Payments",
        compute="_compute_finance_count"
    )

    def _compute_finance_count(self):
        payment_type = self.env['cc.payment.type'].search([
            ('code', '=', 'student_module'),
            ('type_category', '=', 'student')
        ], limit=1)

        for partner in self:
            domain = [("partner_id", "=", partner.id)]
            if payment_type:
                domain.append(("payment_type_id", "=", payment_type.id))

            partner.finance_count = self.env["cc.finance"].search_count(domain)

    student_paid_lessons = fields.Integer(
        string="Paid Lessons",
        compute="_compute_student_lesson_payment_stats",
        store=False,
    )

    student_total_lessons = fields.Integer(
        string="Total Lessons",
        compute="_compute_student_lesson_payment_stats",
        store=False,
    )

    finance_lessons_ratio = fields.Char(
        string="Moliya",
        compute="_compute_student_lesson_payment_stats",
        store=False,
    )

    module_discount_ids = fields.One2many(
        "edu.student.module.discount",
        "student_id",
        string="Modul chegirmalari",
    )

    def _compute_student_lesson_payment_stats(self):
        payment_type = self.env['cc.payment.type'].search([
            ('code', '=', 'student_module'),
            ('type_category', '=', 'student')
        ], limit=1)
        config = self.env['edu.config'].get_config()
        per_lesson = 0.0
        if config and config.module_price and config.lessons_per_module:
            per_lesson = config.module_price / config.lessons_per_module

        for partner in self:
            if not partner.is_student:
                partner.student_paid_lessons = 0
                partner.student_total_lessons = 0
                partner.finance_lessons_ratio = "0/0"
                continue

            group_lines = self.env['edu.group.student'].search([
                ('student_id', '=', partner.id),
                ('state', '!=', 'cancelled'),
            ])
            group_ids = group_lines.mapped('group_id').ids

            total_lessons = self.env['edu.timetable'].search_count([
                ('group_id', 'in', group_ids),
                ('state', 'in', ['completed', 'in_progress']),
            ]) if group_ids else 0

            paid_amount = 0.0
            if payment_type:
                payments = self.env['cc.finance'].search([
                    ('partner_id', '=', partner.id),
                    ('payment_type_id', '=', payment_type.id),
                    ('transaction_type', '=', 'income'),
                    ('state', '=', 'confirmed'),
                ])
                paid_amount = sum(payments.mapped('amount'))

            # Module discounts count as covered amount (up to each
            # enrollment's current module).
            paid_amount += sum(
                line._get_counted_discount_total() for line in group_lines
            )

            paid_lessons = int(paid_amount / per_lesson) if per_lesson > 0 else 0

            partner.student_paid_lessons = paid_lessons
            partner.student_total_lessons = total_lessons
            partner.finance_lessons_ratio = f"{paid_lessons}/{total_lessons}"


    def action_view_partner_finances(self):
        self.ensure_one()
        view_id = self.env.ref(
            "ustudy_group_finance.view_edu_student_lesson_payment_list"
        ).id
        return {
            "name": _("Dars To'lovlari"),
            "type": "ir.actions.act_window",
            "res_model": "edu.student.lesson.payment.report",
            "view_mode": "list",
            "views": [(view_id, "list")],
            "domain": [("student_id", "=", self.id)],
            "context": {"default_student_id": self.id},
        }
