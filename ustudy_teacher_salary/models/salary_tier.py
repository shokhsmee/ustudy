# -*- coding: utf-8 -*-
from odoo import models, fields, api


class TeacherSalaryTier(models.Model):
    """Toifa darajasi (A1..A3, B1..B3).

    ``amount_per_student`` is the authoritative per-student, per-lesson amount
    used in the salary calculation. ``percentage`` is editable metadata shown
    alongside it — the two are intentionally independent (the real figures do
    not derive cleanly from base x %), so both can be edited by hand.
    """
    _name = "edu.teacher.salary.tier"
    _description = "Ustoz oyligi darajasi"
    _order = "category_id, sequence, id"

    name = fields.Char(string="Daraja", required=True, help="Masalan: B3, A1")
    category_id = fields.Many2one(
        "edu.teacher.salary.category", string="Toifa",
        required=True, ondelete="cascade", index=True,
    )
    percentage = fields.Float(
        string="Foiz (%)",
        help="Ushbu darajaning foizi (faqat ma'lumot uchun, tahrirlanadi).",
    )
    amount_per_student = fields.Monetary(
        string="1 o'quvchi uchun summa",
        currency_field="currency_id",
        help="Har o'tilgan dars uchun, aktiv 1 o'quvchiga hisoblanadigan summa. "
             "Hisoblashda aynan shu qiymat ishlatiladi.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    display_name = fields.Char(compute="_compute_display_name", store=True)

    company_id = fields.Many2one(
        "res.company", string="Kompaniya",
        default=lambda self: self.env.company, required=True, index=True,
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id",
        string="Valyuta", readonly=True,
    )

    @api.depends("name", "category_id.name")
    def _compute_display_name(self):
        for rec in self:
            if rec.category_id:
                rec.display_name = "%s / %s" % (rec.category_id.name, rec.name)
            else:
                rec.display_name = rec.name or ""
