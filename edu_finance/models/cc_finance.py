# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.float_utils import float_compare

from odoo.addons.ustudy_group.models.edu_group import edu_admin_locked


class CCFinance(models.Model):
    _name = 'cc.finance'
    _description = 'Finance Record (Income/Expense)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Service #',
        required=True,
        copy=False,
        readonly=True,
        default='New'
    )

    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True
    )

    transaction_type = fields.Selection([
        ('income', 'Income'),
        ('expense', 'Expense')
    ], string='Transaction Type', required=True, default='income', tracking=True)

    partner_id = fields.Many2one(
        'res.partner',
        string='Student/Contact',
        tracking=True
    )

    employee_id = fields.Many2one(
        'hr.employee',
        string='HR Employee',
        tracking=True
    )

    payment_method_id = fields.Many2one(
        'cc.payment.method',
        string='Payment Method',
        required=True,
        tracking=True
    )

    payment_type_id = fields.Many2one(
        'cc.payment.type',
        string='Payment Type',
        required=True,
        tracking=True
    )

    amount = fields.Float(
        string='Amount',
        required=True,
        tracking=True
    )

    balance_amount = fields.Float(
        string='Balance',
        compute='_compute_balance_amount',
        store=True
    )

    description = fields.Text(string='Description', tracking=True)
    notes = fields.Html(string='Notes')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', required=True, tracking=True)

    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True
    )

    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        string='Currency',
        readonly=True
    )

    # ---------------------------------------------------
    # EDUCATION CONNECTION (STUDENT MODULE PAYMENT SNAPSHOT)
    # ---------------------------------------------------
    student_line_id = fields.Many2one(
        "edu.group.student",
        string="Student Group Line",
        ondelete="set null",
        index=True
    )

    group_id = fields.Many2one(
        "edu.group",
        string="Group",
        related="student_line_id.group_id",
        store=True,
        readonly=True
    )

    # IMPORTANT: must be stored snapshot (not related)
    module_id = fields.Many2one(
        "edu.module",
        string="Module",
        ondelete="restrict",
        readonly=True,
        copy=False
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

    @api.model
    def get_finance_dashboard(self, domain=None):
        if domain is None:
            domain = []

        # Always filter only confirmed records
        base_domain = domain + [('state', '=', 'confirmed')]

        records = self.search(base_domain)

        income = sum(records.filtered(lambda r: r.transaction_type == 'income').mapped('amount'))
        expense = sum(records.filtered(lambda r: r.transaction_type == 'expense').mapped('amount'))

        return {
            'income': income,
            'expense': expense,
            'balance': income - expense,
        }

    # ---------------------------------------------------
    # ONCHANGE
    # ---------------------------------------------------
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

    @api.onchange("payment_type_id")
    def _onchange_payment_type(self):
        self.partner_id = False
        self.employee_id = False
        self.student_line_id = False

    # ---------------------------------------------------
    # COMPUTE
    # ---------------------------------------------------
    @api.depends('amount', 'transaction_type')
    def _compute_balance_amount(self):
        for record in self:
            record.balance_amount = record.amount if record.transaction_type == 'income' else -record.amount

    # ---------------------------------------------------
    # CREATE
    # ---------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        # TZ (Administrator roli): payment records are kassa-only. The base
        # ACL gives every internal user create/write on cc.finance, so the
        # Administrator group is locked out again at method level.
        if edu_admin_locked(self.env):
            raise AccessError(_(
                "Administrator to'lov yozuvlarini kirita olmaydi. "
                "Bu kassa vazifasi."
            ))

        for vals in vals_list:

            # sequence
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('cc.finance') or 'New'

            # auto fill student_line_id from partner_id
            if vals.get("partner_id") and not vals.get("student_line_id"):
                line = self.env["edu.group.student"].search([
                    ("student_id", "=", vals["partner_id"]),
                    ("state", "!=", "cancelled")
                ], limit=1)

                if line:
                    vals["student_line_id"] = line.id

            # SNAPSHOT module_id (important)
            if vals.get("student_line_id") and not vals.get("module_id"):
                line = self.env["edu.group.student"].browse(vals["student_line_id"])
                if line.current_module_id:
                    vals["module_id"] = line.current_module_id.id

        return super(CCFinance, self).create(vals_list)

    def write(self, vals):
        # TZ: the Administrator cannot edit payments at all — in particular
        # no back-dating of payment dates and no state manipulation.
        if edu_admin_locked(self.env):
            raise AccessError(_(
                "Administrator to'lov yozuvlarini o'zgartira olmaydi. "
                "Bu kassa vazifasi."
            ))
        return super().write(vals)

    def unlink(self):
        # TZ: "O'chirish — Qat'iyan Yo'q". The ACL already denies unlink to
        # non-system users; this guard keeps it that way even if a broader
        # ACL ever gets added.
        if edu_admin_locked(self.env):
            raise AccessError(_(
                "Administrator to'lov yozuvlarini o'chira olmaydi — "
                "qat'iyan taqiqlangan."
            ))
        return super().unlink()

    # ---------------------------------------------------
    # CONFIRM / CANCEL
    # ---------------------------------------------------
    def action_confirm(self):
        config = self.env['edu.config'].get_config()

        for record in self:
            if record.state != 'draft':
                continue

            # safety: snapshot module_id if empty
            if record.student_line_id and not record.module_id:
                record.module_id = record.student_line_id.current_module_id.id

            # update balances
            if record.partner_id:
                if record.transaction_type == 'income':
                    record.partner_id.finance_balance += record.amount
                else:
                    record.partner_id.finance_balance -= record.amount

            if record.employee_id:
                if record.transaction_type == 'income':
                    record.employee_id.finance_balance += record.amount
                else:
                    record.employee_id.finance_balance -= record.amount

            # UPDATE MODULE PAYMENT ONLY FOR STUDENT MODULE PAYMENTS
            if (
                record.transaction_type == 'income'
                and record.student_line_id
                and record.payment_type_id
                and record.payment_type_id.code == 'student_module'
            ):
                line = record.student_line_id
                target_module = record.module_id or line.current_module_id

                if not target_module:
                    record.state = 'confirmed'
                    record.message_post(body=_("Finance record confirmed. Amount: %s") % record.amount)
                    continue

                # Recompute total paid for the target module from all confirmed records
                # (current record is still 'draft' at this point)
                prior_payments = self.search([
                    ('partner_id', '=', record.partner_id.id),
                    ('module_id', '=', target_module.id),
                    ('payment_type_id', '=', record.payment_type_id.id),
                    ('state', '=', 'confirmed'),
                    ('transaction_type', '=', 'income'),
                    ('id', '!=', record.id),
                ])
                prior_total = sum(prior_payments.mapped('amount'))
                new_total = prior_total + record.amount
                # Cap stored amount at module_price (excess carries to next module)
                stored_amount = min(new_total, config.module_price)

                # Only update student line tracking when paying for the current module
                if target_module == line.current_module_id:
                    vals = {"current_module_payment_amount": stored_amount}

                    if new_total >= config.module_price:
                        vals["current_module_paid"] = True
                        if line.state == "frozen":
                            vals["state"] = "active"

                    line.write(vals)
                # else: payment is a prepayment for a future module;
                # carry-forward is applied in increment_lesson_count when module advances

            record.state = 'confirmed'
            record.message_post(body=_("Finance record confirmed. Amount: %s") % record.amount)

    def action_cancel(self):
        for record in self:
            if record.state == 'confirmed':

                if record.partner_id:
                    if record.transaction_type == 'income':
                        record.partner_id.finance_balance -= record.amount
                    else:
                        record.partner_id.finance_balance += record.amount

                if record.employee_id:
                    if record.transaction_type == 'income':
                        record.employee_id.finance_balance -= record.amount
                    else:
                        record.employee_id.finance_balance += record.amount

            record.state = 'cancelled'
            record.message_post(body=_("Finance record cancelled"))

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    # ---------------------------------------------------
    # CONSTRAINTS
    # ---------------------------------------------------
    @api.constrains('amount')
    def _check_amount(self):
        for record in self:
            if record.amount <= 0:
                raise ValidationError(_("Amount must be greater than zero"))


    @api.constrains("amount", "payment_type_id", "transaction_type")
    def _check_student_module_amount_multiple(self):
        for rec in self:
            if rec.transaction_type != "income":
                continue

            if not rec.payment_type_id or rec.payment_type_id.code != "student_module":
                continue

            config = self.env["edu.config"].get_config()

            if not config.lessons_per_module:
                raise ValidationError(_("Lessons per module is not configured."))

            per_lesson = config.module_price / config.lessons_per_module

            if per_lesson <= 0:
                raise ValidationError(_("Invalid module configuration (per lesson price is 0)."))

            # check amount is multiple of per_lesson
            quotient = rec.amount / per_lesson
            rounded_q = round(quotient)

            if float_compare(quotient, rounded_q, precision_digits=6) != 0:
                raise ValidationError(_(
                    "For Module Payments, amount must be multiple of per-lesson price.\n"
                    "Module price: %(module)s\n"
                    "Lessons: %(lessons)s\n"
                    "Per lesson: %(per)s\n"
                    "Example allowed: %(per)s × lessons"
                ) % {
                    "module": "{:,.0f}".format(config.module_price),
                    "lessons": config.lessons_per_module,
                    "per": "{:,.0f}".format(per_lesson),
                })
