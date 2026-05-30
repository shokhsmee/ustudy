# -*- coding: utf-8 -*-
from odoo import models, fields


class CCPaymentMethod(models.Model):
    """Payment Method (Cash, Bank Transfer, Card, Online Gateway, etc.)

    Extended with a journal_id link: when set, cc.finance uses this journal
    for the generated account.move instead of the company-level default.
    This enables routing "Cash" payments to a cash journal and "Bank Transfer"
    to a bank journal automatically.
    """
    _name = 'cc.payment.method'
    _description = 'Payment Method'
    _order = 'sequence, name'

    name = fields.Char(
        string='Method Name',
        required=True,
        translate=True,
    )
    code = fields.Char(
        string='Code',
        help="Internal code for programmatic lookups (e.g. 'cash', 'bank', 'card').",
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    description = fields.Text(
        string='Description',
    )

    # ------------------------------------------------------------------
    # ACCOUNTING LINK
    # ------------------------------------------------------------------
    journal_id = fields.Many2one(
        'account.journal',
        string='Accounting Journal',
        ondelete='set null',
        help="When set, finance records using this payment method will be "
             "posted to this specific journal. If empty, the system falls "
             "back to the journal configured in Education Configuration or "
             "auto-detects by type (sale/purchase).",
        company_dependent=True,
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    _sql_constraints = [
        ('name_unique', 'unique(name)', 'Payment method name must be unique!'),
    ]
