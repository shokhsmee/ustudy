# -*- coding: utf-8 -*-
from odoo import models, fields, api


class TeacherSalaryCategory(models.Model):
    """Ustoz toifasi (A / B) — base amount for the whole category."""
    _name = "edu.teacher.salary.category"
    _description = "Ustoz oyligi toifasi"
    _order = "sequence, id"

    name = fields.Char(string="Toifa", required=True, help="Masalan: A(toifa), B(toifa)")
    code = fields.Char(string="Kod", help="Qisqa belgi, masalan A yoki B")
    base_amount = fields.Monetary(
        string="Toifa summasi",
        currency_field="currency_id",
        help="Toifaning asosiy summasi (masalan 1 000 000 / 2 000 000). "
             "Faqat ma'lumot uchun — hisoblashda daraja summasi ishlatiladi.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    tier_ids = fields.One2many(
        "edu.teacher.salary.tier", "category_id", string="Darajalar"
    )
    tier_count = fields.Integer(compute="_compute_tier_count", string="Darajalar soni")

    company_id = fields.Many2one(
        "res.company", string="Kompaniya",
        default=lambda self: self.env.company, required=True, index=True,
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id",
        string="Valyuta", readonly=True,
    )

    @api.depends("tier_ids")
    def _compute_tier_count(self):
        for rec in self:
            rec.tier_count = len(rec.tier_ids)
