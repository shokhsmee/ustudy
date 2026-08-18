# -*- coding: utf-8 -*-
from odoo import _, fields, models


class CCFinance(models.Model):
    _inherit = 'cc.finance'

    sale_order_id = fields.Many2one(
        'edu.sale.order',
        string='Sotuv buyurtmasi',
        index=True,
        ondelete='set null',
        copy=False,
        tracking=True,
    )

    def action_open_sale_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Sotuv buyurtmasi"),
            'res_model': 'edu.sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
        }
