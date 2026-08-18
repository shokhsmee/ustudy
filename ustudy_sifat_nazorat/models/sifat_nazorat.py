# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Phone numbers are written in every possible shape on both sides — the
# students' contacts hold "998905001207", "+998934388111", "+998 91 238 26 63"
# and bare "948025101", while OnlinePBX stores "907377987", "998920564807" or
# "+998502210745". The last 9 digits (the national number) are the only part
# that is always present, so they are the matching key.
PHONE_KEY_LEN = 9


class SifatNazorat(models.Model):
    """One quality-control record per absent student per lesson.

    Created automatically when an attendance line is marked "Yo'q" (absent).
    Key info is stored directly (not related) so the record survives even if
    the source attendance is later deleted or left half-created.
    """
    _name = "edu.sifat.nazorat"
    _description = "Sifat nazorati — kelmagan o'quvchi"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, group_id, id desc"

    name = fields.Char(
        string="Yozuv raqami", required=True, copy=False, readonly=True,
        default="New",
    )
    date = fields.Date(string="Sana", required=True, index=True)
    group_id = fields.Many2one(
        "edu.group", string="Guruh", ondelete="set null", index=True,
    )
    student_id = fields.Many2one(
        "res.partner", string="O'quvchi", ondelete="set null", index=True,
    )
    student_phone = fields.Char(
        string="Telefon raqami", compute="_compute_student_phone",
    )
    teacher_id = fields.Many2one(
        "hr.employee", string="Ustoz", ondelete="set null",
    )
    attendance_id = fields.Many2one(
        "edu.attendance", string="Davomat", ondelete="set null",
    )
    attendance_line_id = fields.Many2one(
        "edu.attendance.line", string="Davomat qatori",
        ondelete="set null", index=True, copy=False,
    )
    timetable_id = fields.Many2one(
        "edu.timetable", string="Dars (jadval)", ondelete="set null",
    )
    lesson_no = fields.Integer(string="Dars raqami")
    reason = fields.Selection(
        [("sababli", "Sababli"), ("sababsiz", "Sababsiz")],
        string="Sabab tasnifi", tracking=True,
        help="Bo'sh qolsa — hali tasniflanmagan (kelmadi, sababi aniqlanmagan).",
    )
    state = fields.Selection(
        [("nomalum", "Noma'lum"), ("organib_chiqildi", "O'rganib chiqildi")],
        string="Holat", default="nomalum", required=True, index=True,
        tracking=True,
        help="Noma'lum — hali o'rganilmagan. O'rganib chiqildi — nazorat "
             "yakunlangan (CRM'dagi 'yutildi' kabi ro'yxatdan yashiriladi).",
    )
    # Records are auto-created from attendance (sudo), so no default user —
    # a manager picks up the case by assigning themselves, like CRM leads.
    user_id = fields.Many2one(
        "res.users", string="Mas'ul menejer", tracking=True, index=True,
        domain=[("share", "=", False)],
        help="Shu yozuv ustida ishlayotgan xodim.",
    )
    reason_ids = fields.Many2many(
        "edu.absence.reason",
        "edu_sifat_nazorat_reason_rel", "sn_id", "reason_id",
        string="Sabablari",
        help="Kelmaslik sabablari — katalogdan bir nechta tanlash mumkin.",
    )
    description = fields.Text(string="Tavsif")
    company_id = fields.Many2one(
        "res.company", string="Kompaniya",
        default=lambda self: self.env.company, index=True,
    )

    # Odoo 19 constraint API (old-style _sql_constraints lists are ignored)
    _attendance_line_uniq = models.Constraint(
        "unique(attendance_line_id)",
        "Bitta davomat qatori uchun faqat bitta Sifat Nazorat yozuvi bo'ladi.",
    )

    # ------------------------------------------------------------------
    # OnlinePBX calls (read-only lookup by phone number)
    # ------------------------------------------------------------------
    # No link is stored between a nazorat record and onlinepbx.call: the smart
    # button just FILTERS the call history by the student's number, so calls
    # keep flowing in from the PBX webhook untouched and a phone number fixed
    # on the contact immediately changes what the button shows.
    pbx_call_count = fields.Integer(
        string="Qo'ng'iroqlar", compute="_compute_pbx_call_count",
    )

    @api.depends("student_id.phone")
    def _compute_student_phone(self):
        # Odoo 19: res.partner has no 'mobile' field anymore — phone only
        for rec in self:
            rec.student_phone = rec.student_id.phone or ""

    @api.model
    def _phone_key(self, raw):
        """Last 9 digits of a phone number, or '' when there aren't enough."""
        digits = re.sub(r"\D", "", raw or "")
        return digits[-PHONE_KEY_LEN:] if len(digits) >= PHONE_KEY_LEN else ""

    def _pbx_call_domain(self, key):
        """Calls where the student is the calling or the called party.

        Deliberately NOT matching ``numbers_all``: it also carries the
        company's own external PBX number, which would match every single
        call row for a student whose phone happens to equal it."""
        return ["|", ("from_number", "ilike", key), ("to_number", "ilike", key)]

    @api.depends("student_id.phone")
    def _compute_pbx_call_count(self):
        recs_by_key = {}
        for rec in self:
            rec.pbx_call_count = 0
            key = self._phone_key(rec.student_id.phone)
            if key:
                recs_by_key.setdefault(key, []).append(rec)
        if not recs_by_key or "onlinepbx.call" not in self.env:
            return
        # One query for the whole recordset: a per-record search_count would
        # fire a query per row as soon as this field is put on a list view.
        # Keys are digits only (see _phone_key) and passed as a parameter.
        self.env.cr.execute(
            """
            SELECT k.key, COUNT(c.id)
              FROM unnest(%s::text[]) AS k(key)
              LEFT JOIN onlinepbx_call c
                     ON c.from_number LIKE '%%' || k.key || '%%'
                     OR c.to_number LIKE '%%' || k.key || '%%'
             GROUP BY k.key
            """,
            [list(recs_by_key)],
        )
        for key, count in self.env.cr.fetchall():
            for rec in recs_by_key.get(key, []):
                rec.pbx_call_count = count

    def action_open_pbx_calls(self):
        """Smart button: this student's call history from OnlinePBX."""
        self.ensure_one()
        if "onlinepbx.call" not in self.env:
            raise UserError(_("OnlinePBX moduli o'rnatilmagan."))
        key = self._phone_key(self.student_id.phone)
        if not key:
            raise UserError(_(
                "%s uchun telefon raqami ko'rsatilmagan (yoki juda qisqa) — "
                "qo'ng'iroqlarni filtrlash uchun kontaktga raqam kiriting.",
                self.student_id.display_name or self.name,
            ))
        views = []
        for xmlid, mode in (
            ("onlinepbx_calls.view_onlinepbx_call_list", "list"),
            ("onlinepbx_calls.view_onlinepbx_call_form", "form"),
        ):
            view = self.env.ref(xmlid, raise_if_not_found=False)
            if view:
                views.append((view.id, mode))
        action = {
            "type": "ir.actions.act_window",
            "name": _("Qo'ng'iroqlar — %s") % (self.student_id.display_name or ""),
            "res_model": "onlinepbx.call",
            "view_mode": "list,form",
            "domain": self._pbx_call_domain(key),
            "context": {"create": False},
        }
        if views:
            action["views"] = views
        return action

    def action_mark_organib_chiqildi(self):
        self.write({"state": "organib_chiqildi"})

    def action_mark_nomalum(self):
        self.write({"state": "nomalum"})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "edu.sifat.nazorat"
                ) or "New"
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        # keep the attendance line's reason in sync (guard against ping-pong)
        if (
            ("reason" in vals or "reason_ids" in vals)
            and not self.env.context.get("skip_line_sync")
        ):
            for rec in self:
                line = rec.attendance_line_id
                if not line:
                    continue
                line_vals = {}
                if "reason" in vals and line.absence_reason != rec.reason:
                    line_vals["absence_reason"] = rec.reason
                if "reason_ids" in vals and set(line.absence_reason_ids.ids) != set(rec.reason_ids.ids):
                    line_vals["absence_reason_ids"] = [(6, 0, rec.reason_ids.ids)]
                if line_vals:
                    line.with_context(skip_sn_sync=True).write(line_vals)
        return res

    @api.model
    def get_sn_dashboard(self, domain=None):
        """Counts for the mini dashboard above the list (honours the active
        search filters — same pattern as the finance dashboard)."""
        base = list(domain or [])
        total = self.search_count(base)
        sababli = self.search_count(base + [("reason", "=", "sababli")])
        sababsiz = self.search_count(base + [("reason", "=", "sababsiz")])
        return {
            "total": total,
            "sababli": sababli,
            "sababsiz": sababsiz,
            "unset": total - sababli - sababsiz,
        }
