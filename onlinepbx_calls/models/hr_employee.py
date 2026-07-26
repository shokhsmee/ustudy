from odoo import models, fields, api

class HrEmployee(models.Model):
    _inherit = "hr.employee"

    pbx_extension = fields.Char(
        string="PBX Extension",
        help="Internal PBX extension (e.g. 101, 102) used by the online PBX."
    )

    amocrm_user_id = fields.Integer(
        string="amoCRM User ID",
        help="amoCRM foydalanuvchi IDsi — amoCRM'dan qo'ng'iroqlar sinxronlanganda "
             "mas'ul operator shu ID orqali topiladi.",
    )
    
    call_ids = fields.One2many(
        'onlinepbx.call',
        'employee_id',
        string="Calls",
    )

    rated_call_count = fields.Integer(
        string="Baholangan qo'ng'iroqlar soni",
        compute='_compute_call_stats',
        store=False,
    )

    avg_call_score = fields.Float(
        string="O'rtacha ball",
        compute='_compute_call_stats',
        store=False,
    )

    @api.depends('call_ids.total_score')
    def _compute_call_stats(self):
        for emp in self:
            calls = emp.call_ids
            rated_calls = calls.filtered(lambda c: c.total_score)
            emp.rated_call_count = len(rated_calls)
            emp.avg_call_score = (
                sum(rated_calls.mapped('total_score')) / len(rated_calls)
            ) if rated_calls else 0.0
