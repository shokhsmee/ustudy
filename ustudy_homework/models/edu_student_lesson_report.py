from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError


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

    # Simplified three-way result used by the timetable Vazifalar roster:
    # passed / not passed / failed. "not_passed" covers both the students who
    # never submitted and those who submitted but aren't graded yet.
    result_state = fields.Selection(
        [
            ("passed", "O'tdi"),
            ("not_passed", "O'tmadi"),
            ("failed", "Yiqildi"),
        ],
        string="Natija",
        readonly=True,
    )

    mark = fields.Float(string="Mark", readonly=True)
    student_comment = fields.Text(string="Student Comment", readonly=True)
    teacher_comment = fields.Text(string="Teacher Comment", readonly=True)

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
                    COALESCE(sub.state, 'not_submitted') AS homework_state,
                    CASE
                        WHEN sub.state = 'graded' THEN 'passed'
                        WHEN sub.state = 'failed' THEN 'failed'
                        ELSE 'not_passed'
                    END AS result_state,
                    sub.mark AS mark,
                    sub.comment AS student_comment,
                    sub.teacher_comment AS teacher_comment
                -- One enrollment row per (student, group). Guards against
                -- duplicate edu.group.student records (same student enrolled
                -- twice in one group), which would otherwise double every
                -- lesson row for that student.
                FROM (
                    SELECT DISTINCT ON (student_id, group_id)
                           id, student_id, group_id, enrollment_date
                    FROM edu_group_student
                    ORDER BY student_id, group_id,
                             enrollment_date ASC NULLS FIRST, id ASC
                ) gs
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
                -- One row per student: pick the most relevant submission
                -- (passed first, then failed, then newest) so resubmissions
                -- don't duplicate the student's roster row.
                LEFT JOIN LATERAL (
                    SELECT s.state, s.mark, s.comment, s.teacher_comment
                    FROM edu_homework_submission s
                    WHERE s.homework_id = hw.id AND s.student_id = gs.student_id
                    ORDER BY
                        CASE s.state
                            WHEN 'graded' THEN 0
                            WHEN 'failed' THEN 1
                            WHEN 'submitted' THEN 2
                            ELSE 3
                        END,
                        s.submit_date DESC NULLS LAST,
                        s.id DESC
                    LIMIT 1
                ) sub ON true
            )
        """)

    def write(self, vals):
        """The report is a SQL view, but Ball/Izoh are editable inline in the
        timetable's Vazifalar roster: redirect those two fields to the row's
        real edu.homework.submission — the same record the view's LATERAL
        join shows — creating one when the student never submitted (grading
        on the student's behalf). Submission.create()/write() then handle
        state-from-mark, XP and slide completion. Never calls super():
        UPDATE on the SQL view would fail."""
        editable = {"mark", "teacher_comment"}
        forbidden = set(vals) - editable
        if forbidden:
            raise UserError(_(
                "Bu ro'yxatda faqat Ball va Izoh o'zgartiriladi (%s emas).",
                ", ".join(sorted(forbidden)),
            ))
        if not vals:
            return True
        Submission = self.env["edu.homework.submission"]
        # same relevance order as the view's LATERAL join:
        # graded, failed, submitted, rest — then newest submission first
        state_order = {"graded": 0, "failed": 1, "submitted": 2}

        def sub_sort_key(s):
            ts = s.submit_date.timestamp() if s.submit_date else None
            return (
                state_order.get(s.state, 3),
                -ts if ts is not None else float("inf"),
                -s.id,
            )

        for row in self:
            homework = row.homework_id
            if not homework:
                if not row.slide_id:
                    raise UserError(_(
                        "%s: bu dars uchun \"Dars/Slayd\" tanlanmagan — ball/izoh qo'yib bo'lmaydi.",
                        row.student_id.display_name,
                    ))
                # Grading a lesson whose slide has no homework yet: attach one
                # automatically (named after the slide) so the ball has a
                # submission to live on. edu.homework.create() fills channel /
                # pass_mark defaults and re-syncs timetable homework flags.
                # Search first: row.homework_id is stale within this batch, and
                # grading several students at once must not duplicate it.
                Homework = self.env["edu.homework"]
                homework = Homework.search([
                    ("slide_id", "=", row.slide_id.id),
                    ("is_published", "=", True),
                ], limit=1) or Homework.create({
                    "name": row.slide_id.name,
                    "slide_id": row.slide_id.id,
                })
            subs = Submission.search([
                ("homework_id", "=", homework.id),
                ("student_id", "=", row.student_id.id),
            ])
            if subs:
                min(subs, key=sub_sort_key).write(vals)
            else:
                user = row.student_id.user_ids[:1]
                Submission.create(dict(
                    vals,
                    homework_id=homework.id,
                    student_id=row.student_id.id,
                    user_id=user.id if user else self.env.user.id,
                ))
        return True

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