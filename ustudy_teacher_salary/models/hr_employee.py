# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    salary_tier_id = fields.Many2one(
        "edu.teacher.salary.tier",
        string="Ustoz toifasi/darajasi",
        help="Ushbu ustoz uchun 1 o'quvchi/dars summasini belgilaydigan daraja.",
    )
    teacher_salary_line_ids = fields.One2many(
        "edu.teacher.salary.line", "teacher_id", string="Oylik tranzaksiyalari",
    )
    teacher_salary_earned = fields.Monetary(
        string="Jami ishlagan (earned)",
        compute="_compute_teacher_salary_total", currency_field="currency_id",
        help="Davomat asosida ustoz ishlab topgan jami summa.",
    )
    teacher_salary_paid = fields.Monetary(
        string="To'langan",
        compute="_compute_teacher_salary_total", currency_field="currency_id",
        help="Ustozga haqiqatda to'lab berilgan jami summa (Oylik berish).",
    )
    teacher_salary_total = fields.Monetary(
        string="Qolgan qarz (balans)",
        compute="_compute_teacher_salary_total", currency_field="currency_id",
        help="Ishlab topgan − to'langan = ustozga hali to'lanishi kerak bo'lgan summa.",
    )
    teacher_salary_count = fields.Integer(
        string="Tranzaksiyalar soni", compute="_compute_teacher_salary_total",
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", readonly=True,
    )

    @api.depends(
        "teacher_salary_line_ids.amount_total",
        "teacher_salary_line_ids.state",
        "teacher_salary_line_ids.transaction_type",
    )
    def _compute_teacher_salary_total(self):
        for emp in self:
            # sudo: reading the salary ledger must not raise for HR users who
            # have no finance role.
            confirmed = emp.sudo().teacher_salary_line_ids.filtered(
                lambda l: l.state == "confirmed"
            )
            earned = sum(
                l.amount_total for l in confirmed if l.transaction_type == "kirim"
            )
            paid = sum(
                l.amount_total for l in confirmed if l.transaction_type == "chiqim"
            )
            emp.teacher_salary_earned = earned
            emp.teacher_salary_paid = paid
            emp.teacher_salary_total = earned - paid
            emp.teacher_salary_count = len(confirmed)

    def action_pay_salary(self):
        """Open the 'Oylik berish' wizard to pay this teacher's outstanding
        balance (creates the real Chiqim and settles the ledger)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Oylik berish"),
            "res_model": "edu.teacher.salary.payment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_teacher_id": self.id},
        }

    def action_view_teacher_salary(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Ustoz oyligi",
            "res_model": "edu.teacher.salary.line",
            "view_mode": "list,form",
            "domain": [("teacher_id", "=", self.id)],
            "context": {"default_teacher_id": self.id},
        }
