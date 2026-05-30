# -*- coding: utf-8 -*-
"""Extend edu.config with accounting configuration fields.

These fields control WHERE finance records post to in the standard Odoo
ledger. They are optional — the system auto-detects journals/accounts when
not set — but configuring them gives administrators explicit control.
"""
from odoo import models, fields


class EduConfig(models.Model):
    _inherit = 'edu.config'

    # ------------------------------------------------------------------
    # JOURNAL CONFIGURATION
    # ------------------------------------------------------------------
    income_journal_id = fields.Many2one(
        'account.journal',
        string='Income Journal',
        domain="[('type', '=', 'sale'), ('company_id', '=', company_id)]",
        help="Default journal for student income (out_invoice). "
             "If not set, the system uses the first 'sale' journal of the company.",
    )
    expense_journal_id = fields.Many2one(
        'account.journal',
        string='Expense Journal',
        domain="[('type', '=', 'purchase'), ('company_id', '=', company_id)]",
        help="Default journal for expenses (in_invoice). "
             "If not set, the system uses the first 'purchase' journal of the company.",
    )

    # ------------------------------------------------------------------
    # ACCOUNT CONFIGURATION
    # ------------------------------------------------------------------
    income_account_id = fields.Many2one(
        'account.account',
        string='Income Account',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id), ('deprecated', '=', False)]",
        help="Default income account for invoice lines. If not set, the system "
             "auto-detects the first 'income' account of the company.",
    )
    expense_account_id = fields.Many2one(
        'account.account',
        string='Expense Account',
        domain="[('account_type', '=', 'expense'), ('company_id', '=', company_id), ('deprecated', '=', False)]",
        help="Default expense account for bill lines. If not set, the system "
             "auto-detects the first 'expense' account of the company.",
    )

    # ------------------------------------------------------------------
    # REFUND CONFIGURATION
    # ------------------------------------------------------------------
    refund_journal_id = fields.Many2one(
        'account.journal',
        string='Refund Journal',
        domain="[('type', '=', 'sale'), ('company_id', '=', company_id)]",
        help="Journal for credit notes. If not set, uses the same journal as "
             "the original invoice being reversed.",
    )
    refund_auto_validate = fields.Boolean(
        string='Auto-Validate Approved Refunds',
        default=False,
        help="When enabled, approved refunds are automatically validated "
             "(credit note posted) without a separate validate step.",
    )
