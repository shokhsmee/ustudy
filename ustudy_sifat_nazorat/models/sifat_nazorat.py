# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SifatNazorat(models.Model):
    """One quality-control record per absent student per lesson.

    Created automatically when an attendance line is marked "Yo'q" (absent).
    Key info is stored directly (not related) so the record survives even if
    the source attendance is later deleted or left half-created.
    """
    _name = "edu.sifat.nazorat"
    _description = "Sifat nazorati — kelmagan o'quvchi"
    _inherit = ["mail.thread"]
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
    description = fields.Text(string="Tavsif")
    company_id = fields.Many2one(
        "res.company", string="Kompaniya",
        default=lambda self: self.env.company, index=True,
    )

    _sql_constraints = [
        ("attendance_line_uniq", "unique(attendance_line_id)",
         "Bitta davomat qatori uchun faqat bitta Sifat Nazorat yozuvi bo'ladi."),
    ]

    @api.depends("student_id.phone")
    def _compute_student_phone(self):
        # Odoo 19: res.partner has no 'mobile' field anymore — phone only
        for rec in self:
            rec.student_phone = rec.student_id.phone or ""

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
        if "reason" in vals and not self.env.context.get("skip_line_sync"):
            for rec in self:
                line = rec.attendance_line_id
                if line and line.absence_reason != rec.reason:
                    line.with_context(skip_sn_sync=True).write(
                        {"absence_reason": rec.reason}
                    )
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
