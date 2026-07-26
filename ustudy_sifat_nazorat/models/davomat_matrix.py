# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import UserError


class DavomatMatrix(models.AbstractModel):
    """Enrich the davomat board with absence reasons (Sifat Nazorat):
    per-cell sababli/sababsiz info + a wizard opener for the cell buttons."""
    _inherit = "edu.davomat.matrix"

    @api.model
    def _sn_pick_attendances(self, lesson_ids):
        """Same attendance choice as the base board: confirmed wins, else the
        latest draft — so reasons always match the cells being displayed."""
        atts = self.env["edu.attendance"].search(
            [("timetable_id", "in", lesson_ids),
             ("state", "in", ("draft", "confirmed"))],
            order="id asc",
        )
        chosen, confirmed = {}, set()
        for att in atts:
            tt_id = att.timetable_id.id
            if att.state == "confirmed":
                confirmed.add(tt_id)
            elif tt_id in confirmed:
                continue
            chosen[tt_id] = att
        return chosen

    @api.model
    def get_matrix_data(self, group_id):
        res = super().get_matrix_data(group_id)
        lesson_ids = [l["id"] for m in res["modules"] for l in m["lessons"]]
        chosen = self._sn_pick_attendances(lesson_ids)

        # {student_id: {str(tt_id): reason}}
        reasons_by_student = {}
        for tt_id, att in chosen.items():
            for line in att.attendance_line_ids:
                if line.status == "absent" and line.absence_reason:
                    reasons_by_student.setdefault(
                        line.student_id.id, {}
                    )[str(tt_id)] = line.absence_reason

        today = res.get("today") or {}
        today_reasons = {}
        if today.get("attendance_id"):
            t_att = self.env["edu.attendance"].browse(today["attendance_id"])
            for line in t_att.attendance_line_ids:
                if line.absence_reason:
                    today_reasons[line.student_id.id] = line.absence_reason

        for student in res["students"]:
            sid = student["student_id"]
            student["reasons"] = reasons_by_student.get(sid, {})
            student["today_reason"] = today_reasons.get(sid, False)
        return res

    @api.model
    def matrix_open_reason_wizard(self, timetable_id, student_id):
        """Open the sabab wizard for one student's absence in a lesson."""
        chosen = self._sn_pick_attendances([int(timetable_id)])
        att = chosen.get(int(timetable_id))
        if not att:
            raise UserError(_("Bu dars uchun davomat topilmadi."))
        line = att.attendance_line_ids.filtered(
            lambda l: l.student_id.id == int(student_id)
        )[:1]
        if not line:
            raise UserError(_("O'quvchining davomat qatori topilmadi."))
        return line.action_open_reason_wizard()
