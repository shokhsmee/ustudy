# -*- coding: utf-8 -*-
"""Education Finance Record — the domain-facing orchestration layer.

cc.finance is NOT a ledger. It is a thin wrapper that links education concepts
(student, group, module, payment type/method) to a **real** accounting entry.
When a record is confirmed it generates and posts an ``account.move``
(out_invoice for income, in_invoice for expense). All money lives in
account.move; balances are derived from the ledger, never stored in bespoke
counters.

The student-module payment logic (current_module_paid, carry-forward, freeze/
unfreeze) is handled by ``ustudy_group_finance`` which inherits this model.
This base layer is intentionally agnostic to module-specific education fields
like ``student_line_id`` or ``module_id`` — those are added by the bridge
module.
"""
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools.float_utils import float_compare


class CCFinance(models.Model):
    _name = 'cc.finance'
    _description = 'Finance Record (Income/Expense) — account.move wrapper'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    # ------------------------------------------------------------------
    # CORE FIELDS
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Reference #',
        required=True,
        copy=False,
        readonly=True,
        default='New',
        tracking=True,
    )

    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )

    transaction_type = fields.Selection(
        selection=[
            ('income', 'Income'),
            ('expense', 'Expense'),
        ],
        string='Transaction Type',
        required=True,
        default='income',
        tracking=True,
    )

    partner_id = fields.Many2one(
        'res.partner',
        string='Student / Contact',
        tracking=True,
        index=True,
    )

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        tracking=True,
        index=True,
    )

    payment_method_id = fields.Many2one(
        'cc.payment.method',
        string='Payment Method',
        required=True,
        tracking=True,
    )

    payment_type_id = fields.Many2one(
        'cc.payment.type',
        string='Payment Type',
        required=True,
        tracking=True,
    )

    amount = fields.Float(
        string='Amount',
        required=True,
        tracking=True,
    )

    balance_amount = fields.Float(
        string='Signed Amount',
        compute='_compute_balance_amount',
        store=True,
        help="Positive for income, negative for expense. Used for aggregation.",
    )

    description = fields.Text(
        string='Description',
        tracking=True,
    )

    notes = fields.Html(string='Internal Notes')

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )

    attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Attachments',
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        readonly=True,
        store=True,
    )

    active = fields.Boolean(default=True)

    # ------------------------------------------------------------------
    # LEDGER INTEGRATION (account.move)
    # ------------------------------------------------------------------
    move_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        readonly=True,
        copy=False,
        ondelete='set null',
        index=True,
        help="The posted account.move that represents this record in the "
             "standard Odoo accounting ledger. Created on confirmation.",
    )
    move_state = fields.Selection(
        string='Ledger State',
        related='move_id.state',
        readonly=True,
    )
    move_name = fields.Char(
        string='Ledger Reference',
        related='move_id.name',
        readonly=True,
    )

    # ------------------------------------------------------------------
    # PAYMENT GATEWAY LINK
    # ------------------------------------------------------------------
    gateway_id = fields.Many2one(
        'payment.gateway',
        string='Payment Gateway',
        help="Online payment gateway that originated or verified this payment.",
    )
    gateway_reference = fields.Char(
        string='Gateway Transaction ID',
        copy=False,
        index=True,
        help="External transaction reference returned by the gateway provider.",
    )
    gateway_state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('verified', 'Verified'),
            ('failed', 'Failed'),
        ],
        string='Gateway State',
        copy=False,
    )

    # ------------------------------------------------------------------
    # REFUND TRACKING
    # ------------------------------------------------------------------
    refund_ids = fields.One2many(
        'cc.finance.refund',
        'finance_id',
        string='Refund Requests',
    )
    refunded_amount = fields.Float(
        string='Refunded Amount',
        compute='_compute_refund_info',
        store=True,
        help="Total amount already refunded through validated credit notes.",
    )
    is_refundable = fields.Boolean(
        string='Can Be Refunded',
        compute='_compute_refund_info',
        store=True,
        help="True when record is confirmed income with available un-refunded balance.",
    )
    refund_count = fields.Integer(
        string='Refund Requests',
        compute='_compute_refund_info',
        store=True,
    )

    # ==================================================================
    # COMPUTES
    # ==================================================================
    @api.depends('amount', 'transaction_type')
    def _compute_balance_amount(self):
        for record in self:
            if record.transaction_type == 'income':
                record.balance_amount = record.amount
            else:
                record.balance_amount = -record.amount

    @api.depends(
        'amount',
        'state',
        'transaction_type',
        'refund_ids.state',
        'refund_ids.amount',
    )
    def _compute_refund_info(self):
        for record in self:
            validated_refunds = record.refund_ids.filtered(
                lambda r: r.state == 'validated'
            )
            refunded = sum(validated_refunds.mapped('amount'))
            record.refunded_amount = refunded
            record.refund_count = len(record.refund_ids)
            record.is_refundable = bool(
                record.state == 'confirmed'
                and record.transaction_type == 'income'
                and float_compare(refunded, record.amount, precision_digits=2) < 0
            )

    # ==================================================================
    # ONCHANGE
    # ==================================================================
    @api.onchange('payment_type_id')
    def _onchange_payment_type(self):
        """Reset partner/employee when payment type changes since the
        domain of valid targets differs by type category."""
        self.partner_id = False
        self.employee_id = False

    # ==================================================================
    # CREATE
    # ==================================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Auto-assign sequence number
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('cc.finance') or 'New'
                )
        return super().create(vals_list)

    # ==================================================================
    # LEDGER MOVE GENERATION (Phase 1: Invoice-only)
    # ==================================================================
    def _resolve_move_partner(self):
        """Determine the res.partner to put on the generated account.move.

        Priority:
          1. Explicit partner_id (the student contact).
          2. Employee's work contact (hr.employee -> res.partner).
          3. Company partner as last resort (for partner-less cash movements).
        """
        self.ensure_one()
        if self.partner_id:
            return self.partner_id
        if self.employee_id and self.employee_id.work_contact_id:
            return self.employee_id.work_contact_id
        return self.company_id.partner_id

    def _resolve_journal(self):
        """Pick the accounting journal for this movement.

        Resolution order:
          1. Journal configured on the payment method (most specific).
          2. Journal configured on edu.config (income/expense).
          3. First company journal of the matching type (sale/purchase).
        """
        self.ensure_one()
        # 1. Payment method level
        if hasattr(self.payment_method_id, 'journal_id') and self.payment_method_id.journal_id:
            return self.payment_method_id.journal_id

        # 2. Central education configuration
        config = self.env['edu.config'].get_config()
        if self.transaction_type == 'income' and config.income_journal_id:
            return config.income_journal_id
        if self.transaction_type == 'expense' and config.expense_journal_id:
            return config.expense_journal_id

        # 3. Auto-detect
        journal_type = 'sale' if self.transaction_type == 'income' else 'purchase'
        journal = self.env['account.journal'].search([
            ('type', '=', journal_type),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not journal:
            raise UserError(_(
                "No %(type)s journal found for company '%(company)s'. "
                "Please configure a journal on the Payment Method, in "
                "Education Configuration, or create a %(type)s journal.",
                type=journal_type,
                company=self.company_id.display_name,
            ))
        return journal

    def _resolve_account(self):
        """Pick the income/expense account for the invoice line.

        Resolution order:
          1. Account configured on edu.config (income_account_id / expense_account_id).
          2. First company account of matching type.
        """
        self.ensure_one()
        config = self.env['edu.config'].get_config()
        if self.transaction_type == 'income' and config.income_account_id:
            return config.income_account_id
        if self.transaction_type == 'expense' and config.expense_account_id:
            return config.expense_account_id

        # Auto-detect by account_type
        if self.transaction_type == 'income':
            account_type = 'income'
        else:
            account_type = 'expense'
        account = self.env['account.account'].search([
            ('account_type', '=', account_type),
            ('company_id', '=', self.company_id.id),
            ('deprecated', '=', False),
        ], limit=1)
        if not account:
            raise UserError(_(
                "No %(type)s account found for company '%(company)s'. "
                "Set income/expense accounts in Education Configuration, "
                "or create a Chart of Accounts.",
                type=account_type,
                company=self.company_id.display_name,
            ))
        return account

    def _prepare_move_line_name(self):
        """Build the label for the invoice line."""
        self.ensure_one()
        parts = []
        if self.payment_type_id:
            parts.append(self.payment_type_id.display_name)
        if self.description:
            parts.append(self.description)
        if not parts:
            parts.append(self.name)
        return ' — '.join(parts)

    def _prepare_move_vals(self):
        """Prepare the vals dict for creating the account.move (invoice).

        Phase 1: creates an out_invoice (income) or in_invoice (expense)
        with a single line. Full payment reconciliation (Phase 2) is deferred.
        """
        self.ensure_one()
        journal = self._resolve_journal()
        account = self._resolve_account()
        partner = self._resolve_move_partner()

        move_type = 'out_invoice' if self.transaction_type == 'income' else 'in_invoice'
        line_name = self._prepare_move_line_name()

        return {
            'move_type': move_type,
            'partner_id': partner.id,
            'invoice_date': self.date,
            'date': self.date,
            'journal_id': journal.id,
            'currency_id': self.currency_id.id,
            'ref': self.name,
            'narration': self.description,
            'edu_finance_id': self.id,
            'company_id': self.company_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': line_name,
                'quantity': 1.0,
                'price_unit': self.amount,
                'account_id': account.id,
            })],
        }

    def _generate_ledger_move(self):
        """Create and post the account.move that mirrors this finance record.

        Idempotent: if a move already exists, returns it without creating a
        duplicate. This protects against double-confirm races.
        """
        self.ensure_one()
        if self.move_id:
            return self.move_id
        vals = self._prepare_move_vals()
        move = self.env['account.move'].with_company(self.company_id).create(vals)
        move.action_post()
        self.write({'move_id': move.id})
        return move

    # ==================================================================
    # STATE MACHINE: CONFIRM / CANCEL / RESET
    # ==================================================================
    def action_confirm(self):
        """Confirm the finance record and post it to the accounting ledger.

        This is the single funnel through which all money enters the books:
        manual entry, payment wizard, and gateway verification all call this.
        """
        for record in self.filtered(lambda r: r.state == 'draft'):
            # Generate and post the accounting entry (source of truth)
            record._generate_ledger_move()
            record.state = 'confirmed'
            record.message_post(body=_(
                "Finance record confirmed. Amount: %(amount)s %(currency)s. "
                "Ledger entry: %(move)s.",
                amount="{:,.2f}".format(record.amount),
                currency=record.currency_id.name or '',
                move=record.move_id.name or _('n/a'),
            ))

    def action_cancel(self):
        """Cancel the finance record and neutralize its ledger entry.

        The account.move is NOT deleted (soft lock). It is set to cancel state
        to preserve the audit trail. A credit note (reversal) is the proper
        way to undo the financial effect for reporting purposes.
        """
        for record in self.filtered(lambda r: r.state == 'confirmed'):
            if record.move_id and record.move_id.state == 'posted':
                # Standard Odoo flow: posted -> draft -> cancel
                record.move_id.button_draft()
                record.move_id.button_cancel()
            record.state = 'cancelled'
            record.message_post(body=_(
                "Finance record cancelled. Ledger entry %(move)s neutralized.",
                move=record.move_id.name if record.move_id else _('none'),
            ))

    def action_reset_to_draft(self):
        """Reset a cancelled record back to draft for correction.

        Only allowed when the linked ledger entry is already cancelled.
        """
        for record in self.filtered(lambda r: r.state == 'cancelled'):
            if record.move_id and record.move_id.state not in ('cancel', 'draft'):
                raise UserError(_(
                    "Cannot reset to draft: the linked ledger entry '%(move)s' "
                    "is still %(state)s. Cancel the ledger entry first.",
                    move=record.move_id.name,
                    state=record.move_id.state,
                ))
            record.state = 'draft'
            record.message_post(body=_("Reset to draft."))

    # ==================================================================
    # PAYMENT GATEWAY INTEGRATION
    # ==================================================================
    def action_process_via_gateway(self):
        """Initiate an online payment through the configured gateway adapter.

        The gateway adapter is a plug-and-play interface: cc.finance does not
        know anything about Payme/Click/Uzum specifics. It delegates to the
        abstract ``payment.gateway.adapter`` which concrete providers implement.

        On successful verification the adapter (or webhook controller) calls
        ``action_confirm()`` to post to the ledger.
        """
        self.ensure_one()
        if not self.gateway_id:
            raise UserError(_(
                "No payment gateway is configured on this record. "
                "Please select a gateway before processing."
            ))
        if self.state != 'draft':
            raise UserError(_(
                "Only draft records can be sent to a payment gateway."
            ))
        result = self.gateway_id._dispatch_process_payment({
            'finance_id': self.id,
            'amount': self.amount,
            'currency': self.currency_id.name,
            'partner_id': self.partner_id.id if self.partner_id else False,
            'reference': self.name,
            'description': self.description or '',
        })
        self.write({
            'gateway_reference': result.get('reference', ''),
            'gateway_state': result.get('state', 'pending'),
        })
        return result

    def action_verify_gateway_payment(self):
        """Manually trigger gateway verification (e.g. after timeout).

        Normally the gateway webhook calls verify automatically, but this
        provides a manual fallback.
        """
        self.ensure_one()
        if not self.gateway_id or not self.gateway_reference:
            raise UserError(_("No gateway or transaction reference to verify."))
        result = self.gateway_id._dispatch_verify_payment({
            'finance_id': self.id,
            'reference': self.gateway_reference,
        })
        new_state = result.get('state', 'pending')
        self.gateway_state = new_state
        if new_state == 'verified' and self.state == 'draft':
            self.action_confirm()
        elif new_state == 'failed':
            self.message_post(body=_(
                "Gateway verification failed: %(reason)s",
                reason=result.get('error', _('unknown error')),
            ))
        return result

    # ==================================================================
    # ACTIONS / HELPERS
    # ==================================================================
    def action_view_move(self):
        """Open the linked accounting journal entry."""
        self.ensure_one()
        if not self.move_id:
            raise UserError(_("No ledger entry linked to this record."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entry'),
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_refunds(self):
        """Open refund requests for this finance record."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Refund Requests'),
            'res_model': 'cc.finance.refund',
            'view_mode': 'list,form',
            'domain': [('finance_id', '=', self.id)],
            'context': {
                'default_finance_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_amount': self.amount - self.refunded_amount,
            },
        }

    def action_create_refund(self):
        """Quick-create a refund request for the remaining refundable amount."""
        self.ensure_one()
        if not self.is_refundable:
            raise UserError(_(
                "This record cannot be refunded (either not confirmed, not "
                "income, or already fully refunded)."
            ))
        remaining = self.amount - self.refunded_amount
        refund = self.env['cc.finance.refund'].create({
            'finance_id': self.id,
            'partner_id': self.partner_id.id,
            'amount': remaining,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Refund Request'),
            'res_model': 'cc.finance.refund',
            'res_id': refund.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def get_finance_dashboard(self, domain=None):
        """Return summary figures for the finance dashboard widget."""
        if domain is None:
            domain = []
        base_domain = domain + [('state', '=', 'confirmed')]
        records = self.search(base_domain)
        income = sum(
            records.filtered(lambda r: r.transaction_type == 'income').mapped('amount')
        )
        expense = sum(
            records.filtered(lambda r: r.transaction_type == 'expense').mapped('amount')
        )
        return {
            'income': income,
            'expense': expense,
            'balance': income - expense,
        }

    # ==================================================================
    # CONSTRAINTS
    # ==================================================================
    @api.constrains('amount')
    def _check_amount_positive(self):
        for record in self:
            if float_compare(record.amount, 0.0, precision_digits=2) <= 0:
                raise ValidationError(_(
                    "Amount must be greater than zero. Got: %(amount)s.",
                    amount=record.amount,
                ))

    @api.constrains('amount', 'payment_type_id', 'transaction_type')
    def _check_student_module_amount_multiple(self):
        """Enforce that student module payments are multiples of the per-lesson price.

        This preserves the existing business rule: a module payment must
        correspond to an integer number of lessons.
        """
        for rec in self:
            if rec.transaction_type != 'income':
                continue
            if not rec.payment_type_id or rec.payment_type_id.code != 'student_module':
                continue

            config = self.env['edu.config'].get_config()
            if not config.lessons_per_module:
                raise ValidationError(_(
                    "Education Configuration error: 'Lessons per Module' is "
                    "not set. Please configure it before registering module "
                    "payments."
                ))
            if not config.module_price or config.module_price <= 0:
                raise ValidationError(_(
                    "Education Configuration error: 'Module Price' is not set "
                    "or is zero. Please configure it."
                ))

            per_lesson = config.module_price / config.lessons_per_module
            if per_lesson <= 0:
                raise ValidationError(_(
                    "Computed per-lesson price is zero or negative. Check "
                    "module_price (%(price)s) and lessons_per_module (%(lessons)s).",
                    price=config.module_price,
                    lessons=config.lessons_per_module,
                ))

            quotient = rec.amount / per_lesson
            rounded_q = round(quotient)

            if float_compare(quotient, float(rounded_q), precision_digits=4) != 0:
                raise ValidationError(_(
                    "Module payments must be a multiple of the per-lesson price.\n\n"
                    "Module price: %(module_price)s\n"
                    "Lessons per module: %(lessons)s\n"
                    "Per-lesson price: %(per_lesson)s\n\n"
                    "Your amount (%(amount)s) is not a whole number of lessons.\n"
                    "Allowed examples: %(per_lesson)s, %(double)s, %(triple)s, ...",
                    module_price="{:,.0f}".format(config.module_price),
                    lessons=config.lessons_per_module,
                    per_lesson="{:,.0f}".format(per_lesson),
                    amount="{:,.0f}".format(rec.amount),
                    double="{:,.0f}".format(per_lesson * 2),
                    triple="{:,.0f}".format(per_lesson * 3),
                ))

    # ==================================================================
    # SQL CONSTRAINTS
    # ==================================================================
    _sql_constraints = [
        (
            'gateway_reference_unique',
            'unique(gateway_id, gateway_reference)',
            'A gateway transaction reference must be unique per gateway.',
        ),
    ]
