# -*- coding: utf-8 -*-
from odoo import fields, models


class EduAbsenceReason(models.Model):
    """Catalog of concrete absence reasons (kasallik, oilaviy sabab, ...).

    Managed from the Sifat Nazorat app (Kelmaslik sabablari menu); picked as
    multi-select tags on Sifat Nazorat records, attendance lines and the
    sabab wizard. Complements (does not replace) the sababli/sababsiz
    classification.
    """
    _name = "edu.absence.reason"
    _description = "Kelmaslik sabablari katalogi"
    _order = "sequence, id"

    name = fields.Char(string="Sabab", required=True)
    sequence = fields.Integer(string="Tartib", default=10)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        "unique(name)",
        "Bunday sabab allaqachon mavjud.",
    )
