# -*- coding: utf-8 -*-
"""Education Refund Workflow — approved refunds via Odoo Credit Notes.

State machine:
    draft → pending_approval → approved → validated
                  ↓                          ↑
               rejected                (posts credit note)

The refund is linked to an original cc.finance income record. When validated,
it uses Odoo's standard account.move._reverse_moves() to create a proper
out_refund (credit note) against the original invoice. This preserves the
audit trail and integrates fully with the standard accounting engine.

Approval rules:
  - 'pending_approval' requires at least one attachment (e.g. medical cert).
  - 'approved' transition requires the 'Refund Approver' group.
  - 'validated' posts the credit note to the ledger.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class CCFinanceRefund(models.Model):
    _name = 'cc.finance.refund'
    _description = 'Refund Request (Credit Note Workflow)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    # ------------------------------------------------------------------
    # CORE FIELDS
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Refund #',
        required=True,
        copy=False,
        readonly=True,
        default='New',
        tracking=True,
    )

    finance_id = fields.Many2one(
        'cc.finance',
        string='Original Payment',
        required=True,
        ondelete='restrict',
        index=True,
        domain="[('state', '=', 'confirmed'), ('transaction_type', '=', 'income')]",
        tracking=True,
        help="The confirmed income record to refund (partially or fully).",
    )

    partner_id = fields.Many2one(
        'res.partner',
        string='Student / Contact',
        related='finance_id.partner_id',
        store=True,
        readonly=True,
        index=True,
    )

    amount = fields.Float(
        string='Refund Amount',
        required=True,
        tracking=True,
        help="Amount to refund. Must be > 0 and ≤ the remaining refundable "
             "balance of the original payment.",
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='finance_id.currency_id',
        store=True,
        readonly=True,
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='finance_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )

    reason = fields.Text(
        string='Reason for Refund',
        required=True,
        tracking=True,
        help="Explanation of why the refund is requested.",
    )

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('pending_approval', 'Pending Approval'),
            ('approved', 'Approved'),
            ('validated', 'Validated'),
            ('rejected', 'Rejected'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # ATTACHMENTS (proof documents)
    # ------------------------------------------------------------------
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'cc_finance_refund_attachment_rel',
        'refund_id',
        'attachment_id',
        string='Supporting Documents',
        help="Required proof documents (medical certificate, request letter, "
             "etc.). At least one must be attached before submitting for approval.",
    )
    attachment_count = fields.Integer(
        string='Documents',
        compute='_compute_attachment_count',
        store=False,
    )

    # ------------------------------------------------------------------
    # APPROVAL TRACKING
    # ------------------------------------------------------------------
    submitted_by_id = fields.Many2one(
        'res.users',
        string='Submitted By',
        readonly=True,
        copy=False,
    )
    submitted_date = fields.Datetime(
        string='Submitted Date',
        readonly=True,
        copy=False,
    )
    approved_by_id = fields.Many2one(
        'res.users',
        string='Approved By',
        readonly=True,
        copy=False,
    )
    approved_date = fields.Datetime(
        string='Approved Date',
        readonly=True,
        copy=False,
    )
    validated_by_id = fields.Many2one(
        'res.users',
        string='Validated By',
        readonly=True,
        copy=False,
    )
    validated_date = fields.Datetime(
        string='Validated Date',
        readonly=True,
        copy=False,
    )
    rejected_by_id = fields.Many2one(
        'res.users',
        string='Rejected By',
        readonly=True,
        copy=False,
    )
    rejected_date = fields.Datetime(
        string='Rejected Date',
        readonly=True,
        copy=False,
    )
    rejection_reason = fields.Text(
        string='Rejection Reason',
        tracking=True,
    )

    # ------------------------------------------------------------------
    # CREDIT NOTE LINK
    # ------------------------------------------------------------------
    credit_note_id = fields.Many2one(
        'account.move',
        string='Credit Note',
        readonly=True,
        copy=False,
        ondelete='set null',
        help="The out_refund (credit note) posted when this refund is validated.",
    )
    credit_note_state = fields.Selection(
        string='Credit Note State',
        related='credit_note_id.state',
        readonly=True,
    )

    # ------------------------------------------------------------------
    # ORIGINAL PAYMENT INFO (read-only context)
    # ------------------------------------------------------------------
    original_amount = fields.Float(
        string='Original Amount',
        related='finance_id.amount',
        readonly=True,
    )
    already_refunded = fields.Float(
        string='Already Refunded',
        compute='_compute_already_refunded',
        store=False,
        help="Total previously refunded (validated) for the original payment.",
    )
    max_refundable = fields.Float(
        string='Max Refundable',
        compute='_compute_already_refunded',
        store=False,
    )

    # ==================================================================
    # COMPUTES
    # ==================================================================
    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec.attachment_ids)

    @api.depends('finance_id.amount', 'finance_id.refunded_amount')
    def _compute_already_refunded(self):
        for rec in self:
            orig = rec.finance_id
            if orig:
                # Exclude *this* refund's amount from "already refunded" since
                # it has not been validated yet
                other_validated = orig.refund_ids.filtered(
                    lambda r: r.state == 'validated' and r.id != rec.id
                )
                already = sum(other_validated.mapped('amount'))
                rec.already_refunded = already
                rec.max_refundable = orig.amount - already
            else:
                rec.already_refunded = 0.0
                rec.max_refundable = 0.0

    # ==================================================================
    # CREATE
    # ==================================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('cc.finance.refund')
                    or 'New'
                )
        return super().create(vals_list)

    # ==================================================================
    # STATE TRANSITIONS
    # ==================================================================
    def action_submit(self):
        """draft → pending_approval.

        Gate: at least one supporting document must be attached (e.g. medical
        certificate, student request, internal memo).
        """
        for rec in self.filtered(lambda r: r.state == 'draft'):
            if not rec.attachment_ids:
                raise UserError(_(
                    "Please attach at least one supporting document (e.g. "
                    "medical certificate, student request) before submitting "
                    "for approval."
                ))
            rec._validate_refund_amount()
            rec.write({
                'state': 'pending_approval',
                'submitted_by_id': self.env.uid,
                'submitted_date': fields.Datetime.now(),
            })
            rec.message_post(body=_(
                "Refund request submitted for approval. "
                "Amount: %(amount)s %(currency)s. Reason: %(reason)s",
                amount="{:,.2f}".format(rec.amount),
                currency=rec.currency_id.name or '',
                reason=rec.reason or '',
            ))

    def action_approve(self):
        """pending_approval → approved.

        Gate: requires the 'Refund Approver' group.
        """
        if not self.env.user.has_group('edu_finance.group_refund_approver'):
            raise UserError(_(
                "Only users with the 'Refund Approver' right can approve "
                "refund requests. Please contact your manager."
            ))
        for rec in self.filtered(lambda r: r.state == 'pending_approval'):
            rec._validate_refund_amount()
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.uid,
                'approved_date': fields.Datetime.now(),
            })
            rec.message_post(body=_(
                "Refund approved by %(user)s.",
                user=self.env.user.display_name,
            ))

    def action_validate(self):
        """approved → validated.

        This is the terminal success state. It creates and posts the credit
        note (out_refund) against the original invoice via Odoo's standard
        reversal mechanism.
        """
        for rec in self.filtered(lambda r: r.state == 'approved'):
            rec._validate_refund_amount()
            credit_note = rec._create_credit_note()
            rec.write({
                'state': 'validated',
                'validated_by_id': self.env.uid,
                'validated_date': fields.Datetime.now(),
                'credit_note_id': credit_note.id,
            })
            rec.message_post(body=_(
                "Refund validated. Credit note %(cn)s posted to the ledger. "
                "Amount: %(amount)s %(currency)s.",
                cn=credit_note.name,
                amount="{:,.2f}".format(rec.amount),
                currency=rec.currency_id.name or '',
            ))
            # Also post a note on the original finance record
            rec.finance_id.message_post(body=_(
                "Refund %(refund)s validated: %(amount)s %(currency)s refunded. "
                "Credit note: %(cn)s.",
                refund=rec.name,
                amount="{:,.2f}".format(rec.amount),
                currency=rec.currency_id.name or '',
                cn=credit_note.name,
            ))

    def action_reject(self):
        """pending_approval → rejected (with reason)."""
        for rec in self.filtered(lambda r: r.state == 'pending_approval'):
            if not rec.rejection_reason:
                raise UserError(_(
                    "Please provide a rejection reason before rejecting."
                ))
            rec.write({
                'state': 'rejected',
                'rejected_by_id': self.env.uid,
                'rejected_date': fields.Datetime.now(),
            })
            rec.message_post(body=_(
                "Refund request rejected by %(user)s. Reason: %(reason)s",
                user=self.env.user.display_name,
                reason=rec.rejection_reason,
            ))

    def action_reset_to_draft(self):
        """rejected → draft (to allow re-submission with corrected docs)."""
        for rec in self.filtered(lambda r: r.state == 'rejected'):
            rec.write({
                'state': 'draft',
                'rejection_reason': False,
                'rejected_by_id': False,
                'rejected_date': False,
            })
            rec.message_post(body=_("Reset to draft for re-submission."))

    # ==================================================================
    # CREDIT NOTE GENERATION
    # ==================================================================
    def _create_credit_note(self):
        """Create and post a credit note (out_refund) for the refund amount.

        Uses Odoo's standard reversal mechanism when the refund equals the
        full original amount. For partial refunds, creates a standalone
        out_refund with the partial amount.
        """
        self.ensure_one()
        original_move = self.finance_id.move_id
        if not original_move:
            raise UserError(_(
                "The original payment '%(name)s' has no linked ledger entry. "
                "Cannot create a credit note without an original invoice.",
                name=self.finance_id.name,
            ))
        if original_move.state != 'posted':
            raise UserError(_(
                "The original invoice '%(name)s' is not posted (current state: "
                "%(state)s). It must be posted to create a credit note.",
                name=original_move.name,
                state=original_move.state,
            ))

        is_full_refund = float_compare(
            self.amount, self.finance_id.amount, precision_digits=2
        ) == 0

        if is_full_refund:
            # Use standard reversal for full refunds — cleanest audit trail
            credit_note = self._create_full_reversal(original_move)
        else:
            # Partial refund: create a standalone out_refund
            credit_note = self._create_partial_credit_note(original_move)

        return credit_note

    def _create_full_reversal(self, original_move):
        """Create a full reversal (credit note) of the original invoice.

        Uses account.move._reverse_moves() for a clean, Odoo-standard reversal.
        """
        self.ensure_one()
        reverse_wizard = self.env['account.move.reversal'].with_context(
            active_model='account.move',
            active_ids=original_move.ids,
        ).create({
            'date': fields.Date.context_today(self),
            'reason': _("Refund %(refund)s: %(reason)s", refund=self.name, reason=self.reason or ''),
            'journal_id': original_move.journal_id.id,
        })
        result = reverse_wizard.reverse_moves()

        # The reversal wizard returns an action; extract the created move
        if result.get('res_id'):
            credit_note = self.env['account.move'].browse(result['res_id'])
        elif result.get('domain'):
            # Multiple reversals; find ours
            credit_note = self.env['account.move'].search(
                result['domain'], order='id desc', limit=1
            )
        else:
            raise UserError(_(
                "Failed to create credit note via reversal wizard."
            ))

        # Link back to this refund
        credit_note.write({'edu_refund_id': self.id})

        # Post if not already posted
        if credit_note.state != 'posted':
            credit_note.action_post()

        return credit_note

    def _create_partial_credit_note(self, original_move):
        """Create a partial credit note (standalone out_refund).

        For partial refunds we cannot use a full reversal. Instead we create
        a new out_refund with the partial amount, referencing the original.
        """
        self.ensure_one()
        journal = original_move.journal_id
        partner = original_move.partner_id

        # Use the same income account as the original invoice line
        original_line = original_move.invoice_line_ids[:1]
        account = original_line.account_id if original_line else self.finance_id._resolve_account()

        line_name = _(
            "Partial refund for %(original)s — %(reason)s",
            original=self.finance_id.name,
            reason=self.reason or '',
        )

        credit_note_vals = {
            'move_type': 'out_refund',
            'partner_id': partner.id,
            'invoice_date': fields.Date.context_today(self),
            'date': fields.Date.context_today(self),
            'journal_id': journal.id,
            'currency_id': self.currency_id.id,
            'ref': _("Refund %(refund)s for %(original)s",
                     refund=self.name, original=self.finance_id.name),
            'narration': self.reason,
            'edu_refund_id': self.id,
            'company_id': self.company_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': line_name,
                'quantity': 1.0,
                'price_unit': self.amount,
                'account_id': account.id,
            })],
        }
        credit_note = self.env['account.move'].with_company(
            self.company_id
        ).create(credit_note_vals)
        credit_note.action_post()
        return credit_note

    # ==================================================================
    # VALIDATION HELPERS
    # ==================================================================
    def _validate_refund_amount(self):
        """Ensure the refund amount is valid against the original payment."""
        self.ensure_one()
        if float_compare(self.amount, 0.0, precision_digits=2) <= 0:
            raise ValidationError(_(
                "Refund amount must be greater than zero."
            ))
        max_refundable = self.max_refundable
        if float_compare(self.amount, max_refundable, precision_digits=2) > 0:
            raise ValidationError(_(
                "Refund amount (%(amount)s) exceeds the maximum refundable "
                "balance (%(max)s) for payment '%(payment)s'.\n\n"
                "Original: %(original)s\n"
                "Already refunded: %(refunded)s\n"
                "Maximum you can refund: %(max)s",
                amount="{:,.2f}".format(self.amount),
                max="{:,.2f}".format(max_refundable),
                payment=self.finance_id.name,
                original="{:,.2f}".format(self.finance_id.amount),
                refunded="{:,.2f}".format(self.already_refunded),
            ))

    # ==================================================================
    # ACTIONS
    # ==================================================================
    def action_view_credit_note(self):
        """Open the linked credit note."""
        self.ensure_one()
        if not self.credit_note_id:
            raise UserError(_("No credit note linked to this refund."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Credit Note'),
            'res_model': 'account.move',
            'res_id': self.credit_note_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ==================================================================
    # CONSTRAINTS
    # ==================================================================
    @api.constrains('amount')
    def _check_amount_positive(self):
        for rec in self:
            if float_compare(rec.amount, 0.0, precision_digits=2) <= 0:
                raise ValidationError(_(
                    "Refund amount must be greater than zero."
                ))

    @api.constrains('finance_id')
    def _check_finance_is_refundable(self):
        for rec in self:
            if rec.finance_id.state != 'confirmed':
                raise ValidationError(_(
                    "Can only create refunds for confirmed finance records."
                ))
            if rec.finance_id.transaction_type != 'income':
                raise ValidationError(_(
                    "Can only refund income records (not expenses)."
                ))
