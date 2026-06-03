# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import UserError


class EduGroupStudent(models.Model):
    _inherit = "edu.group.student"

    def _compute_display_name(self):
        for rec in self:
            student = rec.student_id.name or ''
            group = rec.group_id.name or ''
            rec.display_name = f"{student} – {group}" if group else student

    def increment_lesson_count(self):
        """Override to apply carry-forward overpayment when advancing modules."""
        self.ensure_one()

        config = self.env['edu.config'].get_config()

        if not self.current_module_id:
            first_module = self.env["edu.module"].search([], order="sequence asc", limit=1)
            if not first_module:
                raise UserError(_("No modules found. Please create modules first."))
            self.current_module_id = first_module.id

        new_lesson_count = self.lessons_in_current_module + 1

        if new_lesson_count > config.lessons_per_module:

            next_module = self.env["edu.module"].search([
                ("sequence", "=", self.current_module_id.sequence + 1)
            ], limit=1)

            if not next_module:
                raise UserError(_("Next module not found. Please create it."))

            # Compute how much is already available for the next module:
            # 1. Carry-forward from overpayment of the current module
            # 2. Any explicit prepayments already made for the next module
            prepaid_for_next = self._compute_next_module_prepaid(
                next_module, config.module_price
            )
            next_already_paid = prepaid_for_next >= config.module_price

            prev_module_name = self.current_module_id.name

            self.write({
                "current_module_id": next_module.id,
                "lessons_in_current_module": 1,
                "current_module_paid": next_already_paid,
                "current_module_payment_amount": min(prepaid_for_next, config.module_price),
            })

            carry_msg = ""
            if prepaid_for_next > 0:
                carry_msg = _(" | Carry-forward: %s") % "{:,.0f}".format(prepaid_for_next)

            self.group_id.message_post(
                body=_("Student %s completed %s, moved to %s%s") % (
                    self.student_id.name,
                    prev_module_name,
                    next_module.name,
                    carry_msg,
                )
            )
        else:
            self.write({
                "lessons_in_current_module": new_lesson_count
            })

    def _compute_next_module_prepaid(self, next_module, module_price):
        """Compute how much is pre-available for next_module.

        Considers:
        - Overpayment carry from current module (sum_paid_for_current - module_price)
        - Any explicit cc.finance payments already made for next_module
        """
        payment_type = self.env['cc.payment.type'].search([
            ('code', '=', 'student_module'),
        ], limit=1)

        if not payment_type:
            return 0.0

        # Sum of confirmed payments for the current module on THIS enrollment only
        current_payments = self.env['cc.finance'].search([
            ('student_line_id', '=', self.id),
            ('module_id', '=', self.current_module_id.id),
            ('payment_type_id', '=', payment_type.id),
            ('state', '=', 'confirmed'),
            ('transaction_type', '=', 'income'),
        ])
        current_total = sum(current_payments.mapped('amount'))
        overpayment = max(0.0, current_total - module_price)

        # Explicit prepayments for the next module on THIS enrollment only
        next_payments = self.env['cc.finance'].search([
            ('student_line_id', '=', self.id),
            ('module_id', '=', next_module.id),
            ('payment_type_id', '=', payment_type.id),
            ('state', '=', 'confirmed'),
            ('transaction_type', '=', 'income'),
        ])
        explicit_prepaid = sum(next_payments.mapped('amount'))

        return overpayment + explicit_prepaid
