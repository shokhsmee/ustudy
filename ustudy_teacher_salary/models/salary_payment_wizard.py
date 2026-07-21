# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class TeacherSalaryPaymentWizard(models.TransientModel):
    """Oylik berish: pay a teacher's outstanding (earned − paid) balance.

    Creates a settlement transaction in the salary ledger (transaction_type
    'chiqim') which reduces the teacher's balance, and posts the matching real
    company expense (Chiqim / cc.finance). This is the ONLY place a teacher
    salary expense is booked — per-lesson earnings never hit Chiqimlar.
    """
    _name = "edu.teacher.salary.payment.wizard"
    _description = "Ustozga oylik berish"

    teacher_id = fields.Many2one("hr.employee", string="Ustoz", required=True)
    date = fields.Datetime(
        string="To'lov sanasi", required=True, default=fields.Datetime.now,
    )
    amount_due = fields.Monetary(
        string="Qolgan qarz", currency_field="currency_id",
        compute="_compute_amount_due",
    )
    amount = fields.Monetary(
        string="To'lov summasi", currency_field="currency_id", required=True,
    )
    payment_method_id = fields.Many2one("cc.payment.method", string="To'lov usuli")
    note = fields.Text(string="Izoh")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id,
    )

    @api.depends("teacher_id")
    def _compute_amount_due(self):
        for wiz in self:
            wiz.amount_due = wiz.teacher_id.teacher_salary_total if wiz.teacher_id else 0.0

    @api.onchange("teacher_id")
    def _onchange_teacher_id(self):
        # default the payment to the full outstanding balance
        self.amount = self.teacher_id.teacher_salary_total if self.teacher_id else 0.0

    def action_pay(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_("To'lov summasi 0 dan katta bo'lishi kerak."))
        if self.amount > self.amount_due:
            raise UserError(_(
                "To'lov summasi (%(paid)s) ustozning qarzidan (%(due)s) katta "
                "bo'lishi mumkin emas."
            ) % {
                "paid": "{:,.0f}".format(self.amount),
                "due": "{:,.0f}".format(self.amount_due),
            })

        line = self.env["edu.teacher.salary.line"].sudo().create({
            "date": self.date,
            "teacher_id": self.teacher_id.id,
            "teacher_name": self.teacher_id.name,
            "transaction_type": "chiqim",
            "amount_total": self.amount,
            "state": "confirmed",
            "note": self.note or _("Ustozga oylik to'lovi"),
        })
        # Post the real cash expense (Chiqim), honouring the chosen method.
        line._post_expense(method=self.payment_method_id)

        self.teacher_id.message_post(body=_(
            "💸 Oylik to'landi: %(teacher)s — %(amount)s. Qolgan qarz: %(due)s"
        ) % {
            "teacher": self.teacher_id.name,
            "amount": "{:,.0f}".format(self.amount),
            "due": "{:,.0f}".format(self.amount_due - self.amount),
        })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Oylik to'landi"),
                "message": _("%(teacher)s — %(amount)s to'landi.") % {
                    "teacher": self.teacher_id.name,
                    "amount": "{:,.0f}".format(self.amount),
                },
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
