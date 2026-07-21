# -*- coding: utf-8 -*-
import json

from odoo import api, fields, models


class AmocrmEmployee(models.Model):
    """An amoCRM user (xodim) mirrored into Odoo, with a mapping to a res.users.

    Records are created/updated by amocrm.connector.sync_employees(). The
    user_id mapping is what the rest of the integration will use to attribute
    amoCRM data (leads, calls, ...) to the right Odoo user.
    """
    _name = "amocrm.employee"
    _description = "amoCRM xodimi (foydalanuvchi)"
    _order = "name"

    amocrm_id = fields.Integer(string="amoCRM ID", required=True, index=True)
    name = fields.Char(string="Ism", required=True)
    email = fields.Char(string="Email", index=True)
    lang = fields.Char(string="Til")
    is_admin = fields.Boolean(string="amoCRM admin")
    is_active = fields.Boolean(string="Faol", default=True)
    role_name = fields.Char(string="Rol")
    group_name = fields.Char(string="Guruh")
    user_id = fields.Many2one(
        "res.users", string="Odoo foydalanuvchisi", ondelete="set null",
        help="Ushbu amoCRM xodimiga mos keluvchi Odoo foydalanuvchisi.",
    )
    last_sync = fields.Datetime(string="Oxirgi sinxron", readonly=True)
    raw_data = fields.Text(string="Xom ma'lumot (JSON)", readonly=True)
    company_id = fields.Many2one(
        "res.company", string="Kompaniya",
        default=lambda self: self.env.company,
    )

    _sql_constraints = [
        ("amocrm_id_uniq", "unique(amocrm_id)",
         "Bu amoCRM xodimi (ID) allaqachon mavjud."),
    ]

    @api.model
    def _values_from_amocrm(self, u):
        """Map one amoCRM /api/v4/users record to Odoo field values."""
        rights = u.get("rights") or {}
        emb = u.get("_embedded") or {}
        roles = emb.get("roles") or []
        groups = emb.get("groups") or []
        return {
            "amocrm_id": u.get("id"),
            "name": u.get("name") or u.get("email") or ("amoCRM #%s" % u.get("id")),
            "email": u.get("email"),
            "lang": u.get("lang"),
            "is_admin": bool(rights.get("is_admin")),
            "is_active": bool(rights.get("is_active", True)),
            "role_name": roles[0].get("name") if roles else False,
            "group_name": groups[0].get("name") if groups else False,
            "last_sync": fields.Datetime.now(),
            "raw_data": json.dumps(u, ensure_ascii=False, indent=2),
        }

    def _auto_match_user(self):
        """Best-effort link to an Odoo user with the same email/login when the
        mapping is still empty. Never overrides a manual choice."""
        Users = self.env["res.users"].sudo()
        for rec in self:
            if rec.user_id or not rec.email:
                continue
            user = Users.search([
                "|", ("login", "=ilike", rec.email), ("email", "=ilike", rec.email),
            ], limit=1)
            if user:
                rec.user_id = user.id
