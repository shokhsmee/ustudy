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
        Report = self.env["edu.student.lesson.report"]

        for partner in self:
            partner.lesson_homework_count = Report.search_count([
                ("student_id", "=", partner.id)
            ])

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
        Report = self.env["edu.student.lesson.report"]

        for partner in self:
            total = Report.search_count([
                ("student_id", "=", partner.id),
                ("homework_id", "!=", False),
            ])
            passed = Report.search_count([
                ("student_id", "=", partner.id),
                ("homework_state", "=", "graded"),
            ])
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
        Report = self.env["edu.student.lesson.report"]

        for partner in self:
            domain = [
                ("student_id", "=", partner.id),
                ("timetable_state", "in", ["in_progress", "completed"]),
            ]

            total = Report.search_count(domain)

            present = Report.search_count(domain + [
                ("attendance_status", "=", "present")
            ])

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
