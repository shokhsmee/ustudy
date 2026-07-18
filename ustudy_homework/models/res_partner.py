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
        # This drives the "Vazifa holati" column on the Talabalar list. It was
        # 2 search_count()s per row against the heavy edu.student.lesson.report
        # SQL view (~1.8s each) => an 80-row page did ~290s of DB work and hit
        # limit_time_real ("cursor already closed"). Two grouped queries for the
        # whole recordset cost the same ~1.8s each regardless of row count.
        Report = self.env["edu.student.lesson.report"]
        total_map = {}
        passed_map = {}
        if self.ids:
            for student, count in Report._read_group(
                [("student_id", "in", self.ids), ("homework_id", "!=", False)],
                groupby=["student_id"],
                aggregates=["__count"],
            ):
                total_map[student.id] = count
            for student, count in Report._read_group(
                [("student_id", "in", self.ids), ("homework_state", "=", "graded")],
                groupby=["student_id"],
                aggregates=["__count"],
            ):
                passed_map[student.id] = count
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
        # Batched for the same reason as _compute_ops_stats: never run one
        # search_count per row against the edu.student.lesson.report SQL view.
        Report = self.env["edu.student.lesson.report"]
        base = [("timetable_state", "in", ["in_progress", "completed"])]
        total_map = {}
        present_map = {}
        if self.ids:
            for student, count in Report._read_group(
                [("student_id", "in", self.ids)] + base,
                groupby=["student_id"],
                aggregates=["__count"],
            ):
                total_map[student.id] = count
            for student, count in Report._read_group(
                [("student_id", "in", self.ids)] + base
                + [("attendance_status", "=", "present")],
                groupby=["student_id"],
                aggregates=["__count"],
            ):
                present_map[student.id] = count
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
