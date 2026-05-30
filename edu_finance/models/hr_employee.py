# -*- coding: utf-8 -*-
"""Employee finance extensions — ledger-derived balance.

Same pattern as res.partner: ``finance_balance`` is now computed from confirmed
cc.finance records (which have posted account.move entries), not mutated.
"""
from odoo import models, fields, api, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # ------------------------------------------------------------------
    # FINANCE BALANCE — DERIVED, NOT MUTATED
    # ------------------------------------------------------------------
    finance_balance = fields.Float(
        string='Finance Balance',
        compute='_compute_finance_balance',
        store=True,
        readonly=True,
        tracking=True,
        help="Net education finance balance derived from confirmed records. "
             "For employees, income = center pays them, expense = deductions.",
    )

    finance_ids = fields.One2many(
        'cc.finance',
        'employee_id',
        string='Finance Records',
    )

    finance_count = fields.Integer(
        string='Finance Count',
        compute='_compute_finance_count',
        store=False,
    )

    # Admin-only manual adjustment (kept from legacy, applied as a percentage
    # modifier on displayed balance in views — does NOT touch the ledger)
    finance_adjustment = fields.Float(
        string='Finance Adjustment (%)',
        default=0.0,
        tracking=True,
        help="Manual adjustment percentage to employee balance display "
             "(Admin only). Does not affect the accounting ledger.",
    )

    is_user_admin = fields.Boolean(
        string='Is Admin',
        compute='_compute_is_user_admin',
        compute_sudo=False,
    )

    # ------------------------------------------------------------------
    # COMPUTES
    # ------------------------------------------------------------------
    @api.depends(
        'finance_ids.state',
        'finance_ids.balance_amount',
    )
    def _compute_finance_balance(self):
        """Derive balance from confirmed finance records.

        For employees:
          - Income records (center pays employee, e.g. salary): positive.
          - Expense records (deductions from employee): negative.
        This mirrors the partner logic but for the employee ledger.
        """
        for employee in self:
            confirmed = employee.finance_ids.filtered(
                lambda r: r.state == 'confirmed'
            )
            employee.finance_balance = sum(confirmed.mapped('balance_amount'))

    @api.depends('finance_ids')
    def _compute_finance_count(self):
        for employee in self:
            employee.finance_count = len(employee.finance_ids)

    def _compute_is_user_admin(self):
        """Check if current user is administrator."""
        is_admin = self.env.user.has_group('base.group_system')
        for record in self:
            record.is_user_admin = is_admin

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------
    def action_view_finances(self):
        """Open finance records for this employee."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Finance Records'),
            'res_model': 'cc.finance',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }
