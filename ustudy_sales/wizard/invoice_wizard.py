# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EduSaleInvoiceWizard(models.TransientModel):
    _name = 'edu.sale.invoice.wizard'
    _description = "Hisob-faktura yaratish (moliya yozuvi)"

    order_id = fields.Many2one(
        'edu.sale.order',
        string='Buyurtma',
        required=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='order_id.partner_id',
        string='Mijoz',
        readonly=True,
    )
    currency_id = fields.Many2one(
        related='order_id.currency_id',
        readonly=True,
    )
    amount_due = fields.Monetary(
        related='order_id.amount_due',
        string='Qarzdorlik',
        readonly=True,
        currency_field='currency_id',
    )
    amount = fields.Monetary(
        string='Summa',
        required=True,
        currency_field='currency_id',
    )
    payment_method_id = fields.Many2one(
        'cc.payment.method',
        string="To'lov usuli",
        required=True,
    )
    date = fields.Date(
        string='Sana',
        required=True,
        default=fields.Date.context_today,
    )
    description = fields.Text(string='Izoh')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order_id = res.get('order_id') or self.env.context.get('active_id')
        if order_id and 'order_id' in fields_list:
            res['order_id'] = order_id
        if order_id:
            order = self.env['edu.sale.order'].browse(order_id)
            if 'amount' in fields_list and not res.get('amount'):
                res['amount'] = order.amount_due
            if 'description' in fields_list and not res.get('description'):
                courses = ', '.join(
                    order.order_line.mapped('product_id.name'))
                res['description'] = _(
                    "%(order)s buyurtmasi bo'yicha to'lov — %(courses)s",
                    order=order.name, courses=courses)
        if 'payment_method_id' in fields_list and not res.get(
                'payment_method_id'):
            method = self.env['cc.payment.method'].search(
                [('code', '=', 'cash')], limit=1)
            if method:
                res['payment_method_id'] = method.id
        return res

    def _get_payment_type(self):
        payment_type = self.env.ref(
            'ustudy_sales.payment_type_course_sale',
            raise_if_not_found=False)
        if not payment_type:
            PaymentType = self.env['cc.payment.type'].sudo()
            payment_type = PaymentType.search(
                [('code', '=', 'course_sale')], limit=1)
            if not payment_type:
                payment_type = PaymentType.create({
                    'name': 'Kurs sotuvi (buyurtma)',
                    'code': 'course_sale',
                    'direction': 'kirim',
                    'type_category': 'student',
                })
        return payment_type

    def action_create_invoice(self):
        self.ensure_one()
        order = self.order_id
        if order.state != 'confirmed':
            raise UserError(_(
                "Hisob-faktura yaratish uchun buyurtma tasdiqlangan "
                "bo'lishi kerak."))
        if self.amount <= 0:
            raise UserError(_("Summa noldan katta bo'lishi kerak."))

        payment_type = self._get_payment_type()

        # Kassa tasdiqlaydi: yozuv QORALAMA holatda yaratiladi va
        # buyurtmada "Tasdiqlanishi kutilyotgan" bo'lib ko'rinadi.
        # sudo(): cc.finance ACL yozish huquqini sotuv menejeriga
        # bermasdan yozuv yaratish uchun (ustudy_teacher_salary dagi
        # _post_expense bilan bir xil yondashuv).
        finance = self.env['cc.finance'].sudo().create({
            'date': self.date,
            'transaction_type': 'income',
            'partner_id': order.partner_id.id,
            'payment_method_id': self.payment_method_id.id,
            'payment_type_id': payment_type.id,
            'amount': self.amount,
            'description': self.description or '',
            'state': 'draft',
            'company_id': order.company_id.id,
            'sale_order_id': order.id,
        })

        order.message_post(body=_(
            "Hisob-faktura yaratildi: %(name)s — %(amount)s. "
            "Kassa tasdig'i kutilmoqda.",
            name=finance.name,
            amount=f"{self.amount:,.0f}",
        ))
        return {'type': 'ir.actions.act_window_close'}
