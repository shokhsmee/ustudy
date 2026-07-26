from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EduLessonCompleteWizard(models.TransientModel):
    """Darsni yakunlash wizard.

    Opens instead of directly completing a lesson: the teacher defines the
    group's "Dars vazifasi" (an extra, group-scoped edu.homework) and the
    lesson is completed in the same step. Completing without a task stays
    possible via a secondary button.
    """
    _name = "edu.lesson.complete.wizard"
    _description = "Darsni yakunlash — dars vazifasi"

    timetable_id = fields.Many2one(
        "edu.timetable", string="Dars", required=True, ondelete="cascade",
        readonly=True,
    )
    group_id = fields.Many2one(
        related="timetable_id.group_id", string="Guruh", readonly=True)
    slide_id = fields.Many2one(
        related="timetable_id.slide_id", string="Dars mavzusi", readonly=True)

    name = fields.Char(string="Vazifa nomi", required=True)
    description = fields.Text(string="Tavsif")
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "edu_lesson_complete_wizard_attachment_rel",
        "wizard_id",
        "attachment_id",
        string="Fayllar",
    )
    due_date = fields.Date(string="Deadline")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        timetable_id = res.get("timetable_id") or self.env.context.get("default_timetable_id")
        if not timetable_id:
            return res
        tt = self.env["edu.timetable"].browse(timetable_id)
        if "name" in fields_list and not res.get("name"):
            # "Dars raqami, Fan, sana" — e.g. "25-dars, Cyber security 12 Oy, 16.07.2026"
            parts = []
            if tt.lesson_sequence:
                parts.append(_("%s-dars") % tt.lesson_sequence)
            if tt.course_id:
                parts.append(tt.course_id.name)
            date = tt.start_date or fields.Date.context_today(self)
            parts.append(date.strftime("%d.%m.%Y"))
            res["name"] = ", ".join(parts)
        if "due_date" in fields_list and not res.get("due_date"):
            # Default deadline: the group's next lesson, else +2 days.
            next_tt = self.env["edu.timetable"].search([
                ("group_id", "=", tt.group_id.id),
                ("state", "!=", "cancelled"),
                ("start_datetime", ">", tt.start_datetime),
            ], order="start_datetime asc", limit=1)
            if next_tt and next_tt.start_date:
                res["due_date"] = next_tt.start_date
            elif tt.start_date:
                res["due_date"] = tt.start_date + timedelta(days=2)
        return res

    def _complete_lesson(self):
        self.ensure_one()
        return self.timetable_id.with_context(
            skip_lesson_task_wizard=True
        ).action_mark_completed()

    def action_confirm(self):
        """Create the group's Dars vazifasi, then complete the lesson."""
        self.ensure_one()
        tt = self.timetable_id
        if not tt.group_id:
            raise UserError(_("Darsning guruhi topilmadi."))
        homework = self.env["edu.homework"].create({
            "name": self.name,
            "description": self.description,
            "due_date": self.due_date,
            "slide_id": tt.slide_id.id if tt.slide_id else False,
            "group_id": tt.group_id.id,
            "timetable_id": tt.id,
            "teacher_id": tt.teacher_id.id if tt.teacher_id else False,
            "assigned_datetime": fields.Datetime.now(),
            "is_published": True,
            "attachment_ids": [(6, 0, self.attachment_ids.ids)],
        })
        # Re-point the uploaded files at the homework so portal/website access
        # follows the homework record (same as the submission upload flow).
        if self.attachment_ids:
            self.attachment_ids.sudo().write({
                "res_model": "edu.homework",
                "res_id": homework.id,
            })
        res = self._complete_lesson()
        if self.env.context.get("matrix_flow"):
            return self._matrix_end_camera()
        return res

    def action_complete_only(self):
        """Complete the lesson without adding a task (explicit escape hatch)."""
        res = self._complete_lesson()
        if self.env.context.get("matrix_flow"):
            return self._matrix_end_camera()
        return res

    def _matrix_end_camera(self):
        """Davomat board chaining: after completing the lesson, open the
        end-photo camera wizard which confirms the attendance (advancing
        lesson counts + creating the teacher salary snapshot)."""
        att_id = self.env.context.get("matrix_attendance_id")
        if not att_id:
            return {"type": "ir.actions.act_window_close"}
        return {
            "name": _("Capture Teacher End Photo"),
            "type": "ir.actions.act_window",
            "res_model": "edu.camera.end.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_attendance_id": att_id, "matrix_flow": True},
        }
