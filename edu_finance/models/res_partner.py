# -*- coding: utf-8 -*-
"""Partner finance extensions — ledger-derived balance.

The ``finance_balance`` field is now **computed from the posted ledger**
(account.move) rather than mutated in place. It preserves the exact same
semantics as before (income = positive, expense = negative, net sum = balance)
so that existing UI, portal, and report code continues to work unchanged.

The computation reads from cc.finance records in 'confirmed' state and sums
their signed ``balance_amount``. Since every confirmed cc.finance has a posted
account.move behind it, this is equivalent to reading from the ledger — but
faster (no multi-join across account_move_line) and scoped to education
transactions only (not polluted by unrelated accounting entries).
"""
from odoo import models, fields, api, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ------------------------------------------------------------------
    # FINANCE BALANCE — DERIVED, NOT MUTATED
    # ------------------------------------------------------------------
    finance_balance = fields.Float(
        string='Finance Balance',
        compute='_compute_finance_balance',
        store=True,
        readonly=True,
        help="Net education finance balance derived from confirmed records. "
             "Positive = net income received from this student. "
             "Negative = net expenses paid to this contact.",
    )

    finance_ids = fields.One2many(
        'cc.finance',
        'partner_id',
        string='Finance Records',
    )

    finance_count = fields.Integer(
        string='Finance Count',
        compute='_compute_finance_count',
        store=False,
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

        Semantics (unchanged from legacy):
          - Income (student pays us): positive contribution.
          - Expense (we pay out): negative contribution.
          - Cancelled/draft records: excluded.

        This replaces the old ``+= amount`` / ``-= amount`` mutation pattern
        with a clean, race-free, auditable computation.
        """
        for partner in self:
            confirmed = partner.finance_ids.filtered(
                lambda r: r.state == 'confirmed'
            )
            partner.finance_balance = sum(confirmed.mapped('balance_amount'))

    @api.depends('finance_ids')
    def _compute_finance_count(self):
        for partner in self:
            partner.finance_count = len(partner.finance_ids)

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------
    def action_view_finances(self):
        """Open the finance records for this partner."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Finance Records'),
            'res_model': 'cc.finance',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_view_refunds(self):
        """Open refund requests for this partner."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Refund Requests'),
            'res_model': 'cc.finance.refund',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
        }
