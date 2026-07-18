from odoo import api, fields, models


class EduGroupStudent(models.Model):
    _inherit = "edu.group.student"

    vazifa_ratio = fields.Char(
        string="Vazifa holati",
        compute="_compute_vazifa_ratio",
        store=False,
        help="Homework submissions over total assigned homeworks for lessons "
             "that have happened in this group since the student's enrollment "
             "date. Format: 'submitted/total'.",
    )

    def _compute_vazifa_ratio(self):
        Timetable = self.env["edu.timetable"]
        Homework = self.env["edu.homework"]
        Submission = self.env["edu.homework.submission"]

        for rec in self:
            if not rec.group_id or not rec.student_id:
                rec.vazifa_ratio = "0/0"
                continue

            tt_domain = [
                ("group_id", "=", rec.group_id.id),
                ("state", "in", ["in_progress", "completed"]),
                ("slide_id", "!=", False),
            ]
            if rec.enrollment_date:
                tt_domain.append(("start_date", ">=", rec.enrollment_date))

            slide_ids = Timetable.search(tt_domain).mapped("slide_id").ids
            if not slide_ids:
                rec.vazifa_ratio = "0/0"
                continue

            # Course-wide homework plus THIS group's own lesson tasks; other
            # groups' tasks on the shared slides must not inflate the total.
            homeworks = Homework.search([
                ("slide_id", "in", slide_ids),
                ("is_published", "=", True),
                "|",
                ("group_id", "=", False),
                ("group_id", "=", rec.group_id.id),
            ])
            total = len(homeworks)
            if not total:
                rec.vazifa_ratio = "0/0"
                continue

            submitted = Submission.search_count([
                ("homework_id", "in", homeworks.ids),
                ("student_id", "=", rec.student_id.id),
            ])
            rec.vazifa_ratio = f"{submitted}/{total}"
