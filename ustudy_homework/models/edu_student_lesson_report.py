from odoo import api, fields, models, tools, _


class EduStudentLessonReport(models.Model):
    _name = "edu.student.lesson.report"
    _description = "Student Lessons / Homework Report"
    _auto = False
    _rec_name = "timetable_name"
    _order = "start_datetime asc"   # reversed

    student_id = fields.Many2one("res.partner", string="Student", readonly=True)

    timetable_id = fields.Many2one("edu.timetable", string="Lesson", readonly=True)
    timetable_name = fields.Char(string="Lesson Name", readonly=True)

    group_id = fields.Many2one("edu.group", string="Group", readonly=True)
    course_id = fields.Many2one("edu.course", string="Course", readonly=True)

    slide_id = fields.Many2one("slide.slide", string="Lesson Slide", readonly=True)
    homework_id = fields.Many2one("edu.homework", string="Homework", readonly=True)

    start_datetime = fields.Datetime(string="Start Time", readonly=True)
    end_datetime = fields.Datetime(string="End Time", readonly=True)

    timetable_state = fields.Selection(
        [
            ("scheduled", "Scheduled"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        string="Lesson Status",
        readonly=True,
    )

    attendance_status = fields.Selection(
        [
            ("present", "Keldi"),
            ("absent", "Kelmadi"),
        ],
        string="Attendance",
        readonly=True,
    )

    homework_state = fields.Selection(
        [
            ("not_submitted", "Not Submitted"),
            ("submitted", "Submitted"),
            ("graded", "Passed"),
            ("failed", "Failed"),
        ],
        string="Homework Status",
        readonly=True,
    )

    mark = fields.Float(string="Mark", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # filter_guruhga_qoshilgan: a student only sees lessons/homework dated
        # on or after their enrollment_date in the group. Students enrolled at
        # the group's start (enrollment_date NULL or before any timetable) see
        # everything by default.
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    row_number() OVER (ORDER BY tt.start_datetime ASC, tt.id ASC, gs.student_id) AS id,
                    gs.student_id AS student_id,
                    tt.id AS timetable_id,
                    tt.name AS timetable_name,
                    tt.group_id AS group_id,
                    tt.course_id AS course_id,
                    tt.slide_id AS slide_id,
                    hw.id AS homework_id,
                    tt.start_datetime AS start_datetime,
                    COALESCE(tt.end_datetime, tt.start_datetime + INTERVAL '90 minutes') AS end_datetime,
                    tt.state AS timetable_state,
                    al.status AS attendance_status,
                    CASE
                        WHEN sub.id IS NULL THEN 'not_submitted'
                        ELSE sub.state
                    END AS homework_state,
                    sub.mark AS mark
                FROM edu_group_student gs
                JOIN edu_timetable tt ON tt.group_id = gs.group_id
                    AND (
                        gs.enrollment_date IS NULL
                        OR tt.start_datetime >= gs.enrollment_date::timestamp
                    )
                LEFT JOIN edu_attendance att
                    ON att.timetable_id = tt.id AND att.state = 'confirmed'
                LEFT JOIN edu_attendance_line al
                    ON al.attendance_id = att.id AND al.student_id = gs.student_id
                LEFT JOIN edu_homework hw
                    ON hw.slide_id = tt.slide_id AND hw.is_published = true
                LEFT JOIN edu_homework_submission sub
                    ON sub.homework_id = hw.id AND sub.student_id = gs.student_id
            )
        """)

    @api.model
    def filter_guruhga_qoshilgan(self, domain=None, student_id=None):
        """Return a domain scoped to a single student's lesson report rows.

        The SQL view itself already excludes lessons dated before each student's
        enrollment_date (see init() — the join condition enforces it). So all
        this helper has to do is anchor the search to the right student. It
        exists as a named entry point so callers (controllers, dashboards) can
        rely on a single canonical way to filter "lessons since the student
        joined the group" — matching the requested method name."""
        domain = list(domain or [])
        if student_id:
            partner_id = student_id
        else:
            partner = self.env.user.partner_id
            partner_id = partner.id if partner else False
        if not partner_id:
            return domain
        return domain + [("student_id", "=", partner_id)]


    @api.model
    def get_attendance_dashboard(self, student_id=False):
        done_domain = [("timetable_state", "in", ["in_progress", "completed"])]
        if student_id:
            done_domain.append(("student_id", "=", student_id))

        total = self.search_count(done_domain)
        present = self.search_count(done_domain + [("attendance_status", "=", "present")])
        absent = total - present
        percent = round((present / total * 100)) if total > 0 else 0

        all_domain = [("student_id", "=", student_id)] if student_id else []
        graded_records = self.search(all_domain + [("mark", ">", 0)])
        obs = round(sum(graded_records.mapped("mark")) / len(graded_records), 1) if graded_records else 0.0

        return {
            "total": total,
            "present": present,
            "absent": absent,
            "davomat_foizi": f"{percent}%",
            "obs": obs,
        }