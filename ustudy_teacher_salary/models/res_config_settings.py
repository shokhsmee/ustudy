# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    teacher_salary_active_basis = fields.Selection(
        [
            ("present", "Davomat qilgan o'quvchilar (present)"),
            ("enrolled", "Faol biriktirilgan o'quvchilar (enrolled)"),
        ],
        string="Aktiv o'quvchi hisoblash usuli",
        default="enrolled",
        config_parameter="ustudy_teacher_salary.active_basis",
        help="Ustoz oyligi qaysi o'quvchilar soniga hisoblanadi: darsda davomat "
             "qilgan (present) yoki guruhga faol biriktirilgan (enrolled).",
    )
    teacher_salary_default_method_id = fields.Many2one(
        "cc.payment.method",
        string="Oylik uchun standart to'lov usuli",
        config_parameter="ustudy_teacher_salary.default_method_id",
        help="'Oylik berish'da Chiqim yozuvi uchun standart to'lov usuli.",
    )
