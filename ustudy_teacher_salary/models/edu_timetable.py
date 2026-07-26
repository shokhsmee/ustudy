# -*- coding: utf-8 -*-
from odoo import models, fields, api


class EduTimetable(models.Model):
    """Connect each lesson (timetable) with its teacher-salary transaction and
    surface the transaction status in the attendance section."""
    _inherit = "edu.timetable"

    salary_line_id = fields.Many2one(
        "edu.teacher.salary.line",
        string="Ustoz oyligi tranzaksiyasi",
        compute="_compute_salary_line", store=True,
        help="Ushbu dars uchun yaratilgan ustoz oyligi (kirim) tranzaksiyasi.",
    )
    direct_salary_line_ids = fields.One2many(
        "edu.teacher.salary.line", "timetable_id",
        string="Oylik tranzaksiyalari (to'g'ridan-to'g'ri)",
        help="Ushbu darsga bevosita bog'langan tranzaksiyalar — davomatsiz "
             "(qo'lda) yaratilganlar ham shu yerdan ko'rinadi.",
    )
    salary_state = fields.Selection(
        [
            ("draft", "Qoralama"),
            ("confirmed", "Tasdiqlangan"),
            ("cancelled", "Bekor qilingan"),
        ],
        string="Oylik holati", compute="_compute_salary_line", store=True,
    )
    salary_amount = fields.Float(
        string="Oylik summasi", compute="_compute_salary_line", store=True,
    )

    @api.depends(
        "attendance_ids.salary_line_id",
        "attendance_ids.salary_line_id.state",
        "attendance_ids.salary_line_id.amount_total",
        "direct_salary_line_ids.state",
        "direct_salary_line_ids.amount_total",
    )
    def _compute_salary_line(self):
        for tt in self:
            lines = (tt.attendance_ids.mapped("salary_line_id")
                     | tt.direct_salary_line_ids.filtered(
                         lambda l: l.transaction_type == "kirim"))
            line = lines.filtered(lambda l: l.state == "confirmed")[:1] or lines[:1]
            tt.salary_line_id = line.id if line else False
            tt.salary_state = line.state if line else False
            tt.salary_amount = line.amount_total if line else 0.0

    @api.depends("group_id.name", "start_datetime")
    @api.depends_context("salary_lesson_picker")
    def _compute_display_name(self):
        """In the salary-transaction lesson picker every weekly slot shares the
        same "Group - Weekday HH:MM" label; show lesson no + real date instead
        so an old lesson can actually be identified."""
        if not self.env.context.get("salary_lesson_picker"):
            return super()._compute_display_name()
        for tt in self:
            parts = [tt.group_id.name or "?"]
            if tt.lesson_sequence:
                parts.append("№%s" % tt.lesson_sequence)
            if tt.start_datetime:
                local_dt = fields.Datetime.context_timestamp(tt, tt.start_datetime)
                parts.append(local_dt.strftime("%d.%m.%Y %H:%M"))
            tt.display_name = " — ".join(parts)

    def action_open_salary_line(self):
        self.ensure_one()
        if not self.salary_line_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": "Ustoz oyligi tranzaksiyasi",
            "res_model": "edu.teacher.salary.line",
            "res_id": self.salary_line_id.id,
            "view_mode": "form",
            "target": "current",
        }
