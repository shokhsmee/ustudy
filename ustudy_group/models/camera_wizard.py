from odoo import api, fields, models, _
from odoo.exceptions import UserError


class CameraWizard(models.TransientModel):
    _name = 'edu.camera.wizard'
    _description = 'Teacher Camera Capture'

    timetable_id = fields.Many2one('edu.timetable', string='Lesson', required=True)
    teacher_image = fields.Binary("Teacher Photo")
    # System admins may start a lesson without a photo — the form surfaces the
    # "Start" button immediately for them (see camera_wizard.js).
    is_admin = fields.Boolean(compute="_compute_is_admin")

    def _compute_is_admin(self):
        is_admin = self.env.user.has_group("base.group_system")
        for rec in self:
            rec.is_admin = is_admin

    def action_capture_and_start(self):
        """Save image and create attendance"""
        self.ensure_one()

        is_admin = self.env.user.has_group("base.group_system")

        # If not admin, photo is required
        if not is_admin and not self.teacher_image:
            raise UserError(_("Please capture teacher photo first."))

        vals = {
            "timetable_id": self.timetable_id.id,
        }

        # If teacher photo exists, save it
        if self.teacher_image:
            vals.update({
                "teacher_start_image": self.teacher_image,
                "teacher_start_image_filename": f"teacher_start_{fields.Datetime.now()}.jpg",
            })

        # Create attendance record
        attendance = self.env["edu.attendance"].create(vals)

        # Create attendance lines for active students. One line per distinct
        # student: duplicated enrollment lines (historic data) would otherwise
        # create duplicate lines and confirm would advance that student's
        # lesson count twice per lesson (this is how the U18 drift happened).
        attendance_lines = []
        seen_students = set()
        for student_line in self.timetable_id.group_id.student_line_ids.filtered(lambda s: s.state == "active"):
            if student_line.student_id.id in seen_students:
                continue
            seen_students.add(student_line.student_id.id)
            attendance_lines.append((0, 0, {
                "student_id": student_line.student_id.id,
                "status": "present",
            }))

        if attendance_lines:
            attendance.write({"attendance_line_ids": attendance_lines})

        # Mark lesson as in progress
        self.timetable_id.write({"state": "in_progress"})

        # Matrix flow (davomat board): just close the dialog — the board
        # reloads and shows the attendance selectors inline in today's column.
        if self.env.context.get("matrix_flow"):
            return {"type": "ir.actions.act_window_close"}

        # Open attendance form
        return {
            "name": _("Mark Attendance"),
            "type": "ir.actions.act_window",
            "res_model": "edu.attendance",
            "res_id": attendance.id,
            "view_mode": "form",
            "target": "current",
        }
