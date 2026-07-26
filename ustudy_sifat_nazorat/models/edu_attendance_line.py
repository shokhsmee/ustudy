# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class EduAttendanceLine(models.Model):
    _inherit = "edu.attendance.line"

    absence_reason = fields.Selection(
        [("sababli", "Sababli"), ("sababsiz", "Sababsiz")],
        string="Sabab",
        help="Yo'q (kelmadi) uchun sabab tasnifi. Bo'sh — tasniflanmagan.",
    )

    # ------------------------------------------------------------------
    # Sifat Nazorat sync: absent line <-> one edu.sifat.nazorat record
    # ------------------------------------------------------------------
    def _sn_date(self):
        self.ensure_one()
        att = self.attendance_id
        return (
            att.attendance_date
            or (att.timetable_id.start_date if att.timetable_id else False)
            or fields.Date.context_today(self)
        )

    def _sync_sifat_nazorat(self):
        """Ensure absent lines have a Sifat Nazorat record (and its reason
        matches); drop the record when the student is no longer absent.
        Fields are read via the timetable as fallback because half-created
        attendances can miss the stored related group/teacher/date."""
        SN = self.env["edu.sifat.nazorat"].sudo()
        existing = {
            sn.attendance_line_id.id: sn
            for sn in SN.search([("attendance_line_id", "in", self.ids)])
        }
        for line in self:
            sn = existing.get(line.id)
            if line.status == "absent":
                att = line.attendance_id
                tt = att.timetable_id
                if not sn:
                    SN.create({
                        "date": line._sn_date(),
                        "group_id": (att.group_id.id or (tt.group_id.id if tt else False)),
                        "student_id": line.student_id.id,
                        "teacher_id": (att.teacher_id.id or (tt.teacher_id.id if tt else False)),
                        "attendance_id": att.id,
                        "attendance_line_id": line.id,
                        "timetable_id": tt.id if tt else False,
                        "lesson_no": tt.lesson_sequence if tt else 0,
                        "reason": line.absence_reason or False,
                    })
                elif sn.reason != line.absence_reason:
                    sn.with_context(skip_line_sync=True).write(
                        {"reason": line.absence_reason or False}
                    )
            elif sn:
                # marked present again — the absence never happened
                sn.unlink()

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get("skip_sn_sync"):
            absent = lines.filtered(lambda l: l.status == "absent")
            if absent:
                absent._sync_sifat_nazorat()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if (
            not self.env.context.get("skip_sn_sync")
            and ("status" in vals or "absence_reason" in vals)
        ):
            self._sync_sifat_nazorat()
        return res

    def action_open_reason_wizard(self):
        """Sabab tanlash wizard'i (davomat satridagi tugmadan)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sabab tasnifi"),
            "res_model": "edu.absence.reason.wizard",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {"default_line_id": self.id},
        }
