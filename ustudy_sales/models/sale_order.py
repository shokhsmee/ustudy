# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EduSaleOrder(models.Model):
    _name = 'edu.sale.order'
    _description = "Sotuv buyurtmasi"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_order desc, id desc'

    name = fields.Char(
        string='Raqam',
        required=True,
        copy=False,
        readonly=True,
        default='New',
    )
    state = fields.Selection([
        ('draft', 'Qoralama'),
        ('confirmed', 'Tasdiqlangan'),
        ('cancelled', 'Bekor qilingan'),
    ], string='Holat', default='draft', required=True, copy=False,
        index=True, tracking=True)

    partner_id = fields.Many2one(
        'res.partner',
        string='Mijoz',
        required=True,
        index=True,
        tracking=True,
    )
    partner_phone = fields.Char(
        related='partner_id.phone',
        string='Telefon',
        readonly=True,
    )
    date_order = fields.Datetime(
        string='Sana',
        required=True,
        default=fields.Datetime.now,
        tracking=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Sotuvchi',
        default=lambda self: self.env.user,
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Kompaniya',
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        string='Valyuta',
        readonly=True,
    )
    # Videodagi jadval ustunlari: sotuv turi (pryamoy / demo) va guruh
    sale_type = fields.Selection([
        ('direct', "To'g'ridan-to'g'ri sotuv"),
        ('demo', "Ochiq dars / Demo orqali"),
    ], string='Sotuv turi', tracking=True)
    group_id = fields.Many2one(
        'edu.group',
        string='Guruh',
        tracking=True,
    )
    note = fields.Html(string='Izoh')

    order_line = fields.One2many(
        'edu.sale.order.line',
        'order_id',
        string='Buyurtma qatorlari',
        copy=True,
    )

    finance_ids = fields.One2many(
        'cc.finance',
        'sale_order_id',
        string="Moliya yozuvlari",
        copy=False,
    )
    finance_count = fields.Integer(
        string="To'lovlar soni",
        compute='_compute_finance_count',
    )

    # ---------------- totals ----------------
    amount_gross = fields.Monetary(
        string='Summa (chegirmasiz)',
        compute='_compute_amounts', store=True,
        currency_field='currency_id',
    )
    discount_total = fields.Monetary(
        string='Chegirma',
        compute='_compute_amounts', store=True,
        currency_field='currency_id',
    )
    amount_total = fields.Monetary(
        string='Jami',
        compute='_compute_amounts', store=True,
        currency_field='currency_id',
        tracking=True,
    )

    # ---------------- payment info ----------------
    paid_amount = fields.Monetary(
        string="To'langan",
        compute='_compute_payment_amounts', store=True,
        currency_field='currency_id',
        help="Tasdiqlangan moliya yozuvlari (kirim) jami.",
    )
    pending_amount = fields.Monetary(
        string='Tasdiqlanishi kutilyotgan',
        compute='_compute_payment_amounts', store=True,
        currency_field='currency_id',
        help="Kassa hali tasdiqlamagan (qoralama) moliya yozuvlari jami.",
    )
    amount_due = fields.Monetary(
        string='Qarzdorlik',
        compute='_compute_payment_amounts', store=True,
        currency_field='currency_id',
        help="Buyurtma jamisidan to'langan va tasdiqlanishi kutilyotgan "
             "summalar ayirilgan qoldiq.",
    )
    overpaid_amount = fields.Monetary(
        string="Ortiqcha to'langan",
        compute='_compute_payment_amounts', store=True,
        currency_field='currency_id',
        help="Buyurtma jamisidan ortiqcha to'langan summa.",
    )
    # Ro'yxatdagi "Qarzdorlik" ustuni: qarz, yoki mijoz ortiqcha to'lagan
    # bo'lsa — o'sha summa (yashil). Har doim >= 0; hisob-kitob uchun
    # amount_due / overpaid_amount dan foydalaning, bu maydondan emas.
    amount_due_display = fields.Monetary(
        string='Qarzdorlik',
        compute='_compute_payment_amounts', store=True,
        currency_field='currency_id',
    )
    payment_state = fields.Selection([
        ('not_paid', "To'lanmagan"),
        ('partial', "Qisman to'lov"),
        ('paid', "100% to'lov"),
        ('overpaid', "Ortiqcha to'lov"),
    ], string="To'lov holati",
        compute='_compute_payment_state', store=True)

    # ------------------------------------------------------------------
    # COMPUTES
    # ------------------------------------------------------------------
    @api.depends('finance_ids')
    def _compute_finance_count(self):
        for order in self:
            order.finance_count = len(order.finance_ids)

    @api.depends('order_line.price_subtotal', 'order_line.price_unit',
                 'order_line.quantity')
    def _compute_amounts(self):
        for order in self:
            gross = sum(line.quantity * line.price_unit
                        for line in order.order_line)
            total = sum(order.order_line.mapped('price_subtotal'))
            currency = order.currency_id
            if currency:
                gross = currency.round(gross)
                total = currency.round(total)
            order.amount_gross = gross
            order.amount_total = total
            order.discount_total = gross - total

    @api.depends('amount_total', 'finance_ids.state', 'finance_ids.amount',
                 'finance_ids.transaction_type')
    def _compute_payment_amounts(self):
        for order in self:
            paid = pending = 0.0
            for fin in order.finance_ids:
                sign = 1.0 if fin.transaction_type == 'income' else -1.0
                if fin.state == 'confirmed':
                    paid += sign * fin.amount
                elif fin.state == 'draft':
                    pending += sign * fin.amount
            currency = order.currency_id
            due = (order.amount_total or 0.0) - paid - pending
            if currency:
                due = currency.round(due)
            order.paid_amount = paid
            order.pending_amount = pending
            order.amount_due = due if due > 0 else 0.0
            order.overpaid_amount = -due if due < 0 else 0.0
            order.amount_due_display = abs(due)

    @api.depends('amount_total', 'paid_amount')
    def _compute_payment_state(self):
        for order in self:
            currency = order.currency_id
            total = order.amount_total or 0.0
            paid = order.paid_amount or 0.0
            if currency:
                paid_is_zero = currency.is_zero(paid) or paid < 0
                cmp_paid_total = currency.compare_amounts(paid, total)
            else:
                paid_is_zero = paid <= 0
                cmp_paid_total = (paid > total) - (paid < total)
            if paid_is_zero:
                order.payment_state = 'not_paid'
            elif cmp_paid_total < 0:
                order.payment_state = 'partial'
            elif cmp_paid_total == 0:
                order.payment_state = 'paid'
            else:
                order.payment_state = 'overpaid'

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') in (False, 'New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'edu.sale.order') or 'New'
        return super().create(vals_list)

    def unlink(self):
        for order in self:
            if order.state == 'confirmed':
                raise UserError(_(
                    "Tasdiqlangan buyurtmani o'chirib bo'lmaydi. "
                    "Avval bekor qiling."))
            if order.finance_ids:
                raise UserError(_(
                    "Moliya yozuvlari bog'langan buyurtmani o'chirib "
                    "bo'lmaydi."))
        return super().unlink()

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------
    def action_confirm(self):
        for order in self:
            if order.state != 'draft':
                continue
            if not order.order_line:
                raise UserError(_(
                    "Buyurtmani tasdiqlash uchun kamida bitta qator "
                    "kiriting."))
            order.state = 'confirmed'
        return True

    def action_cancel(self):
        for order in self:
            if order.finance_ids.filtered(lambda f: f.state == 'confirmed'):
                raise UserError(_(
                    "Tasdiqlangan to'lovlari bor buyurtmani bekor qilib "
                    "bo'lmaydi. Avval moliya yozuvlarini kassada bekor "
                    "qiling."))
            order.state = 'cancelled'
        return True

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})
        return True

    def action_create_invoice(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_(
                "Hisob-faktura yaratish uchun avval buyurtmani "
                "tasdiqlang."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Hisob-faktura yaratish"),
            'res_model': 'edu.sale.invoice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_order_id': self.id,
            },
        }

    def action_view_finance(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Moliya yozuvlari"),
            'res_model': 'cc.finance',
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {
                'default_sale_order_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_transaction_type': 'income',
            },
        }


class EduSaleOrderLine(models.Model):
    _name = 'edu.sale.order.line'
    _description = "Sotuv buyurtmasi qatori"
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one(
        'edu.sale.order',
        string='Buyurtma',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(string='Tartib', default=10)
    product_id = fields.Many2one(
        'product.product',
        string='Kurs / Mahsulot',
        required=True,
    )
    name = fields.Text(string='Tavsif')
    quantity = fields.Float(
        string='Miqdor',
        required=True,
        default=1.0,
    )
    price_unit = fields.Float(
        string='Narx',
        required=True,
        default=0.0,
    )
    discount = fields.Float(
        string='Chegirma (%)',
        default=0.0,
    )
    currency_id = fields.Many2one(
        related='order_id.currency_id',
        string='Valyuta',
        readonly=True,
    )
    company_id = fields.Many2one(
        related='order_id.company_id',
        string='Kompaniya',
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        related='order_id.state',
        string='Holat',
        store=True,
        readonly=True,
    )
    price_subtotal = fields.Monetary(
        string='Summa',
        compute='_compute_price_subtotal', store=True,
        currency_field='currency_id',
    )

    @api.depends('quantity', 'price_unit', 'discount')
    def _compute_price_subtotal(self):
        for line in self:
            subtotal = (line.quantity * line.price_unit
                        * (1.0 - (line.discount or 0.0) / 100.0))
            if line.currency_id:
                subtotal = line.currency_id.round(subtotal)
            line.price_subtotal = subtotal

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.name = line.product_id.display_name
                line.price_unit = line.product_id.lst_price

    @api.constrains('discount')
    def _check_discount(self):
        for line in self:
            if line.discount < 0 or line.discount > 100:
                raise ValidationError(_(
                    "Chegirma 0 va 100 foiz oralig'ida bo'lishi kerak."))

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_(
                    "Miqdor noldan katta bo'lishi kerak."))
