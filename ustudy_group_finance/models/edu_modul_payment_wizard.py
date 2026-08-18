# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class EduModulePaymentWizard(models.TransientModel):
    _name = 'edu.module.payment.wizard'
    _description = 'Register Module Payment'

    student_line_id = fields.Many2one(
        'edu.group.student',
        string='Student',
        required=True
    )

    student_name = fields.Char(
        related='student_line_id.student_name',
        string='Student Name',
        readonly=True
    )

    group_name = fields.Char(
        related='student_line_id.group_id.name',
        string='Group',
        readonly=True
    )

    module_id = fields.Many2one(
        "edu.module",
        string="Module",
        required=True,
        readonly=True
    )

    module_number = fields.Integer(
        related="module_id.sequence",
        string="Module Number",
        readonly=True
    )

    amount = fields.Float(
        string='Amount',
        required=True
    )

    payment_method_id = fields.Many2one(
        'cc.payment.method',
        string='Payment Method',
        required=True
    )

    payment_date = fields.Date(
        string='Payment Date',
        default=fields.Date.context_today,
        required=True
    )

    is_full_payment = fields.Boolean(
        string='Mark as Fully Paid (Override)',
        default=False,
        help='Force mark module as fully paid even if amount is less than module price'
    )

    notes = fields.Text(string='Notes')

    current_paid = fields.Float(
        related='student_line_id.current_module_payment_amount',
        string='Already Paid',
        readonly=True
    )

    module_price = fields.Float(
        related='student_line_id.module_price',
        string='Module Price',
        readonly=True
    )

    discount_amount = fields.Float(
        string='Chegirma',
        compute='_compute_discount_info',
        help="Discount set for this student's group module "
             "(Talaba formasi → Moliya sahifasi).",
    )

    effective_price = fields.Float(
        string="To'lanishi kerak",
        compute='_compute_discount_info',
        help='Module price minus the discount for this student.',
    )

    remaining_amount = fields.Float(
        string='Qolgan summa',
        compute='_compute_discount_info',
        help='Discounted module price minus what is already paid.',
    )

    @api.depends('student_line_id', 'module_id', 'current_paid')
    def _compute_discount_info(self):
        for wiz in self:
            if wiz.student_line_id and wiz.module_id:
                discount = wiz.student_line_id._get_module_discount_amount(wiz.module_id)
                effective = wiz.student_line_id._get_effective_module_price(wiz.module_id)
            else:
                discount = 0.0
                effective = wiz.module_price
            wiz.discount_amount = discount
            wiz.effective_price = effective
            wiz.remaining_amount = max(0.0, effective - wiz.current_paid)

    # --------------------------
    # MODULE CHANGE PART
    # --------------------------
    update_module = fields.Boolean(
        string="Update Student Module",
        default=False
    )

    new_module_id = fields.Many2one(
        "edu.module",
        string="New Module"
    )

    @api.constrains("update_module", "new_module_id")
    def _check_new_module(self):
        for rec in self:
            if rec.update_module and not rec.new_module_id:
                raise ValidationError(_("Please select New Module."))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        # Default payment method = cash
        payment_method = self.env['cc.payment.method'].search([('code', '=', 'cash')], limit=1)
        if payment_method:
            res['payment_method_id'] = payment_method.id

        # Default module_id from student_line_id
        if res.get("student_line_id"):
            student_line = self.env["edu.group.student"].browse(res["student_line_id"])
            if student_line.current_module_id:
                res["module_id"] = student_line.current_module_id.id

            # Default amount = remaining sum after the module discount.
            # Overrides the caller's default_amount (full config price) so
            # discounted students are charged the discounted remainder.
            if "amount" in fields_list and res.get("module_id"):
                module = self.env["edu.module"].browse(res["module_id"])
                effective = student_line._get_effective_module_price(module)
                remaining = max(
                    0.0, effective - student_line.current_module_payment_amount
                )
                res["amount"] = remaining

        return res

    def action_register_payment(self):
        """Register the module payment"""
        self.ensure_one()

        config = self.env['edu.config'].get_config()

        if not self.module_id:
            raise UserError(_("Module is not selected."))

        # Get or create payment type for student module payment
        payment_type = self.env['cc.payment.type'].search([
            ('code', '=', 'student_module'),
            ('type_category', '=', 'student')
        ], limit=1)

        if not payment_type:
            payment_type = self.env['cc.payment.type'].create({
                'name': 'Student Module Payment',
                'code': 'student_module',
                'type_category': 'student',
            })

        # Create finance record (INCOME - student paying to center)
        description_parts = [
            _('%s payment - %s') % (self.module_id.name, self.group_name)
        ]
        if self.notes:
            description_parts.append(self.notes)

        line = self.student_line_id
        was_frozen = line.state == 'frozen'

        finance = self.env['cc.finance'].create({
            'date': self.payment_date,
            'transaction_type': 'income',
            'partner_id': line.student_id.id,
            'student_line_id': line.id,
            'module_id': self.module_id.id,
            'payment_method_id': self.payment_method_id.id,
            'payment_type_id': payment_type.id,
            'amount': self.amount,
            'description': '\n'.join(description_parts),
            'state': 'draft',
        })

        # action_confirm (edu_finance) updates the student line itself:
        # recomputes the module total from all confirmed records, caps the
        # stored amount at the DISCOUNTED module price, sets the paid flag
        # and unfreezes. The wizard must NOT add the amount again on top
        # (doing both double-counted current_module_payment_amount).
        finance.action_confirm()

        new_payment_amount = line.current_module_payment_amount
        effective_price = line._get_effective_module_price(self.module_id)

        # Admin override: force mark as paid even if below the (discounted) price
        vals = {}
        if self.is_full_payment and not line.current_module_paid:
            vals['current_module_paid'] = True
            if line.state == 'frozen':
                vals['state'] = 'active'
        if vals:
            line.write(vals)

        # Snapshot before a possible module change resets the flag
        module_fully_paid = line.current_module_paid
        unfrozen = was_frozen and line.state == 'active'

        # If user selected module update
        if self.update_module and self.new_module_id:
            self.student_line_id.write({
                "current_module_id": self.new_module_id.id,
                "lessons_in_current_module": 0,
                "current_module_paid": False,
                "current_module_payment_amount": 0.0,
            })

        # Post message to group
        message_parts = [
            _("💰 Module Payment Registered"),
            _("Student: %s") % self.student_line_id.student_id.name,
            _("Module: %s") % self.module_id.name,
            _("Amount: %s") % "{:,.2f}".format(self.amount),
            _("Total Paid: %s / %s") % (
                "{:,.2f}".format(new_payment_amount),
                "{:,.2f}".format(effective_price)
            )
        ]

        discount = self.student_line_id._get_module_discount_amount(self.module_id)
        if discount:
            message_parts.append(
                _("💸 Chegirma: %s (modul narxi %s)") % (
                    "{:,.2f}".format(discount),
                    "{:,.2f}".format(config.module_price),
                )
            )

        if module_fully_paid:
            message_parts.append(_("✅ Module fully paid"))
            if unfrozen:
                message_parts.append(_("🔓 Student unfrozen"))

        if self.update_module and self.new_module_id:
            message_parts.append(_("🔄 Module changed to: %s") % self.new_module_id.name)

        self.student_line_id.group_id.message_post(body='\n'.join(message_parts))

        return {'type': 'ir.actions.act_window_close'}
