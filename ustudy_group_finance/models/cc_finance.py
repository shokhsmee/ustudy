# -*- coding: utf-8 -*-
from odoo import models, fields, api


class CCFinance(models.Model):
    _inherit = "cc.finance"

    student_line_id = fields.Many2one(
        "edu.group.student",
        string="Student Group Line",
        ondelete="set null",
        index=True,
        readonly=False,
    )

    group_id = fields.Many2one(
        "edu.group",
        string="Group",
        related="student_line_id.group_id",
        store=True,
        readonly=True
    )

    module_id = fields.Many2one(
        "edu.module",
        string="Module",
        ondelete="restrict",
        readonly=False,
        copy=False,
        domain="[('active', '=', True)]",
    )

    student_status = fields.Selection(
        related="student_line_id.state",
        string="Student Status",
        store=True,
        readonly=True
    )

    payment_status = fields.Selection(
        related="student_line_id.payment_status",
        string="Payment Status",
        store=True,
        readonly=True
    )

    payment_type_code = fields.Char(
        related='payment_type_id.code',
        string='Payment Type Code',
        store=False,
        readonly=True,
    )

    payment_type_category = fields.Selection(
        related='payment_type_id.type_category',
        string='Payment Type Category',
        store=False,
        readonly=True,
    )

    # ---- Module Payment Summary (computed, no store) ----

    module_already_paid = fields.Float(
        string="Already Paid",
        compute="_compute_module_payment_info",
        store=False,
    )

    module_remaining = fields.Float(
        string="Remaining",
        compute="_compute_module_payment_info",
        store=False,
    )

    module_paid_lessons = fields.Integer(
        string="Paid Lessons",
        compute="_compute_module_payment_info",
        store=False,
    )

    module_lessons_total = fields.Integer(
        string="Total Lessons",
        compute="_compute_module_payment_info",
        store=False,
    )

    module_payment_status = fields.Selection([
        ('not_started', 'Not Started'),
        ('partial', 'Partial'),
        ('paid', 'Fully Paid'),
    ], string="Module Status", compute="_compute_module_payment_info", store=False)

    @api.depends("partner_id", "module_id", "student_line_id", "amount", "state")
    def _compute_module_payment_info(self):
        payment_type = self.env['cc.payment.type'].search([
            ('code', '=', 'student_module'),
        ], limit=1)
        config = self.env['edu.config'].get_config()
        module_price = config.module_price or 0.0
        lessons_per_module = config.lessons_per_module or 12
        per_lesson = module_price / lessons_per_module if lessons_per_module else 0.0

        for rec in self:
            already_paid = 0.0

            if rec.partner_id and rec.module_id and payment_type and rec.student_line_id:
                domain = [
                    ('student_line_id', '=', rec.student_line_id.id),
                    ('module_id', '=', rec.module_id.id),
                    ('payment_type_id', '=', payment_type.id),
                    ('state', '=', 'confirmed'),
                    ('transaction_type', '=', 'income'),
                ]
                if rec.id:
                    domain.append(('id', '!=', rec.id))
                payments = self.env['cc.finance'].search(domain)
                already_paid = sum(payments.mapped('amount'))

            # Cap at module price (excess carries to next module)
            already_paid_capped = min(already_paid, module_price)
            remaining = max(0.0, module_price - already_paid_capped)
            paid_lessons = int(already_paid_capped / per_lesson) if per_lesson else 0

            if already_paid_capped <= 0:
                status = 'not_started'
            elif already_paid_capped >= module_price:
                status = 'paid'
            else:
                status = 'partial'

            rec.module_already_paid = already_paid_capped
            rec.module_remaining = remaining
            rec.module_paid_lessons = min(paid_lessons, lessons_per_module)
            rec.module_lessons_total = lessons_per_module
            rec.module_payment_status = status

    @api.onchange("student_line_id")
    def _onchange_student_line_id_set_module(self):
        for rec in self:
            if rec.student_line_id:
                rec.module_id = rec.student_line_id.current_module_id.id
            else:
                rec.module_id = False

    @api.onchange("partner_id")
    def _onchange_partner_id_set_student_line(self):
        for rec in self:
            rec.student_line_id = False

            if not rec.partner_id:
                continue

            line = self.env["edu.group.student"].search([
                ("student_id", "=", rec.partner_id.id),
                ("state", "!=", "cancelled")
            ], limit=1)

            if line:
                rec.student_line_id = line.id
