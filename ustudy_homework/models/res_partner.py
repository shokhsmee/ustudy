# res_partner.py
from odoo import api, fields, models, _


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ----------------------------
    # Existing Smart Button
    # ----------------------------
    homework_count = fields.Integer(
        string="Homeworks",
        compute="_compute_homework_count",
        store=False,
    )

    def _compute_homework_count(self):
        Homework = self.env["edu.homework"]
        Enrollment = self.env["edu.enrollment"]

        for partner in self:
            enrollments = Enrollment.search([("student_id", "=", partner.id)])
            channel_ids = enrollments.mapped("course_id.slide_channel_id").ids

            partner.homework_count = Homework.search_count([
                ("channel_id", "in", channel_ids),
                ("is_published", "=", True),
            ])

    def action_open_student_homework_submissions(self):
        self.ensure_one()

        enrollments = self.env["edu.enrollment"].search([("student_id", "=", self.id)])
        channel_ids = enrollments.mapped("course_id.slide_channel_id").ids

        student_list_view = self.env.ref(
            "ustudy_homework.view_edu_homework_tree_student",
            raise_if_not_found=False
        )

        action = {
            "name": _("My Homeworks"),
            "type": "ir.actions.act_window",
            "res_model": "edu.homework",
            "domain": [
                ("channel_id", "in", channel_ids),
                ("is_published", "=", True),
            ],
            "context": {
                "default_student_id": self.id,
                "student_view": True,
            },
            "view_mode": "list,form",
        }

        if student_list_view:
            action["views"] = [(student_list_view.id, "list"), (False, "form")]

        return action

    # ----------------------------
    # NEW Smart Button: Vazifalar
    # ----------------------------
    lesson_homework_count = fields.Integer(
        string="Vazifalar",
        compute="_compute_lesson_homework_count",
        store=False,
    )

    def _compute_lesson_homework_count(self):
        # Batched: edu.student.lesson.report is a heavy SQL view (~22k rows,
        # ~1.8s to materialize). One grouped query for the whole recordset
        # costs the same as a single per-row search_count, so never loop.
        Report = self.env["edu.student.lesson.report"]
        counts = {}
        if self.ids:
            for student, count in Report._read_group(
                [("student_id", "in", self.ids)],
                groupby=["student_id"],
                aggregates=["__count"],
            ):
                counts[student.id] = count
        for partner in self:
            partner.lesson_homework_count = counts.get(partner.id, 0)

    ops_passed_count = fields.Integer(
        string="Passed Homeworks",
        compute="_compute_ops_stats",
        store=False,
    )

    ops_total_count = fields.Integer(
        string="Total Homeworks",
        compute="_compute_ops_stats",
        store=False,
    )

    ops_ratio = fields.Char(
        string="Vazifalar",
        compute="_compute_ops_stats",
        store=False,
    )

    def _compute_ops_stats(self):
        # This drives the "Vazifa holati" column on the Talabalar list. The
        # view is expensive to materialize, so it is scanned exactly ONCE:
        # a single grouped query with FILTER clauses instead of two
        # _read_group calls (each of which re-ran the whole view).
        total_map = {}
        passed_map = {}
        if self.ids:
            self.env.cr.execute("""
                SELECT student_id,
                       COUNT(*) FILTER (WHERE homework_id IS NOT NULL),
                       COUNT(*) FILTER (WHERE homework_state = 'graded')
                FROM edu_student_lesson_report
                WHERE student_id IN %s
                GROUP BY student_id
            """, [tuple(self.ids)])
            for sid, total, passed in self.env.cr.fetchall():
                total_map[sid] = total
                passed_map[sid] = passed
        for partner in self:
            total = total_map.get(partner.id, 0)
            passed = passed_map.get(partner.id, 0)
            partner.ops_total_count = total
            partner.ops_passed_count = passed
            partner.ops_ratio = f"{passed}/{total}"

    def action_open_student_lessons_report(self):
        self.ensure_one()

        list_view = self.env.ref(
            "ustudy_homework.view_edu_student_lesson_report_list",
            raise_if_not_found=False
        )

        action = {
            "name": _("Vazifalar"),
            "type": "ir.actions.act_window",
            "res_model": "edu.student.lesson.report",
            "domain": [("student_id", "=", self.id)],
            "context": {"default_student_id": self.id},
            "view_mode": "list",
        }

        if list_view:
            action["views"] = [(list_view.id, "list")]

        return action
    
    
    # ----------------------------
    # NEW Smart Button: Attendance 7/10
    # ----------------------------
    attendance_present_count = fields.Integer(
        string="Present Lessons",
        compute="_compute_attendance_stats",
        store=False,
    )

    attendance_total_count = fields.Integer(
        string="Total Lessons",
        compute="_compute_attendance_stats",
        store=False,
    )

    attendance_ratio = fields.Char(
        string="Attendance",
        compute="_compute_attendance_stats",
        store=False,
    )

    def _compute_attendance_stats(self):
        # Same single-scan pattern as _compute_ops_stats: one grouped query
        # with FILTER clauses, never two passes over the SQL view.
        total_map = {}
        present_map = {}
        if self.ids:
            self.env.cr.execute("""
                SELECT student_id,
                       COUNT(*) FILTER (
                           WHERE timetable_state IN ('in_progress', 'completed')),
                       COUNT(*) FILTER (
                           WHERE timetable_state IN ('in_progress', 'completed')
                             AND attendance_status = 'present')
                FROM edu_student_lesson_report
                WHERE student_id IN %s
                GROUP BY student_id
            """, [tuple(self.ids)])
            for sid, total, present in self.env.cr.fetchall():
                total_map[sid] = total
                present_map[sid] = present
        for partner in self:
            total = total_map.get(partner.id, 0)
            present = present_map.get(partner.id, 0)
            partner.attendance_total_count = total
            partner.attendance_present_count = present
            partner.attendance_ratio = f"{present}/{total}"
    
    def action_open_student_attendance_report(self):
        self.ensure_one()

        list_view = self.env.ref(
            "ustudy_homework.view_edu_student_attendance_report_list",
            raise_if_not_found=False
        )

        action = {
            "name": _("Attendance"),
            "type": "ir.actions.act_window",
            "res_model": "edu.student.lesson.report",
            "domain": [("student_id", "=", self.id)],
            "context": {"default_student_id": self.id},
            "view_mode": "list",
        }

        if list_view:
            action["views"] = [(list_view.id, "list")]

        return action
