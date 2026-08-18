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
            ("not_submitted", "Topshirmagan"),
            ("submitted", "Topshirgan"),
            ("resubmitted", "Qayta topshirgan"),
            ("graded", "O'tgan"),
            ("failed", "Yiqilgan"),
        ],
        string="Topshirish holati",
        readonly=True,
    )

    # Simplified three-way result used by the timetable Vazifalar roster:
    # passed / not passed / failed. "not_passed" covers both the students who
    # never submitted and those who submitted but aren't graded yet — the
    # homework_state column above tells those two apart (and flags retries).
    result_state = fields.Selection(
        [
            ("passed", "O'tdi"),
            ("not_passed", "O'tmadi"),
            ("failed", "Yiqildi"),
        ],
        string="Natija",
        readonly=True,
    )

    # The student's LATEST attempt at this lesson's homework — the row the
    # roster displays and the one the grading dialog / inline Ball edit write
    # to. Empty for students who never submitted.
    submission_id = fields.Many2one(
        "edu.homework.submission", string="Oxirgi topshiriq", readonly=True)
    submit_date = fields.Datetime(string="Topshirilgan vaqt", readonly=True)
    attempt_no = fields.Integer(string="Urinish", readonly=True)

    mark = fields.Float(string="Mark", readonly=True)
    student_comment = fields.Text(string="Student Comment", readonly=True)
    teacher_comment = fields.Text(string="Teacher Comment", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # filter_guruhga_qoshilgan: a student only sees lessons/homework dated
        # on or after their enrollment_date in the group. Students enrolled at
        # the group's start (enrollment_date NULL or before any timetable) see
        # everything by default.
        # Supporting indexes for the view's joins/LATERALs. Without them the
        # per-row LATERAL lookups seq-scan (submissions had no homework_id
        # index, enrollments no student_id index) and every query against the
        # view costs seconds.
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS edu_group_student_student_group_idx
                ON edu_group_student (student_id, group_id);
            CREATE INDEX IF NOT EXISTS edu_homework_submission_hw_student_idx
                ON edu_homework_submission (homework_id, student_id);
            CREATE INDEX IF NOT EXISTS edu_homework_slide_published_idx
                ON edu_homework (slide_id) WHERE is_published = true;
        """)
        # id is a deterministic expression, NOT row_number(): a window
        # function over the whole view blocks predicate pushdown, so even
        # "WHERE student_id IN (...)" had to materialize all ~22k rows.
        # With a plain expression Postgres pushes student/timetable filters
        # into the joins and only computes the requested rows. Unique since
        # student ids stay far below 1e6; stable across queries (row_number
        # wasn't), which the inline-grading write() also benefits from.
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    (tt.id::bigint * 1000000 + gs.student_id) AS id,
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
                    sub.id AS submission_id,
                    sub.submit_date AS submit_date,
                    COALESCE(sub.attempt_no, 0) AS attempt_no,
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
                -- Exactly ONE homework per lesson row: the lesson's own group
                -- task (timetable_id = tt.id) wins over the course-wide slide
                -- homework; other groups'/lessons' group tasks (group_id set)
                -- never match. LATERAL + LIMIT 1 also guards against row
                -- duplication when a slide carries several published homeworks.
                LEFT JOIN LATERAL (
                    SELECT h.id
                    FROM edu_homework h
                    WHERE h.is_published = true
                      AND (
                            h.timetable_id = tt.id
                            OR (tt.slide_id IS NOT NULL
                                AND h.slide_id = tt.slide_id
                                AND h.group_id IS NULL
                                AND h.timetable_id IS NULL)
                      )
                    ORDER BY CASE WHEN h.timetable_id = tt.id THEN 0 ELSE 1 END,
                             h.id
                    LIMIT 1
                ) hw ON true
                -- One row per student: the student's LATEST attempt. Ordering
                -- by state (passed first) would pin the roster to an older
                -- verdict and hide a retry — a student who resubmits after
                -- being failed must show up as 'resubmitted' (needs grading),
                -- not as the previous "Yiqildi".
                LEFT JOIN LATERAL (
                    SELECT s.id, s.state, s.mark, s.comment, s.teacher_comment,
                           s.submit_date, s.attempt_no
                    FROM edu_homework_submission s
                    WHERE s.homework_id = hw.id AND s.student_id = gs.student_id
                    ORDER BY s.submit_date DESC NULLS LAST, s.id DESC
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

        # same order as the view's LATERAL join: the student's newest attempt
        def sub_sort_key(s):
            ts = s.submit_date.timestamp() if s.submit_date else None
            return (-ts if ts is not None else float("inf"), -s.id)

        for row in self:
            homework = row._resolve_homework()
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

    def _resolve_homework(self):
        """The homework a ball on this row belongs to, creating it if needed.

        Grading a lesson whose slide has no homework yet attaches one
        automatically (named after the slide) so the ball has a submission to
        live on. edu.homework.create() fills channel / pass_mark defaults and
        re-syncs the timetable homework flags. Search first: row.homework_id is
        stale within a write batch, and grading several students at once must
        not duplicate it. Same preference order as the SQL view: the lesson's
        own group task, then the course-wide slide homework — never another
        group's."""
        self.ensure_one()
        if self.homework_id:
            return self.homework_id
        if not self.slide_id:
            raise UserError(_(
                "%s: bu dars uchun \"Dars/Slayd\" tanlanmagan — ball/izoh qo'yib bo'lmaydi.",
                self.student_id.display_name,
            ))
        Homework = self.env["edu.homework"]
        return Homework.search([
            ("timetable_id", "=", self.timetable_id.id),
            ("is_published", "=", True),
        ], limit=1) or Homework.search([
            ("slide_id", "=", self.slide_id.id),
            ("is_published", "=", True),
            ("group_id", "=", False),
        ], limit=1) or Homework.create({
            "name": self.slide_id.name,
            "slide_id": self.slide_id.id,
        })

    def action_open_grading(self):
        """Row button of the timetable Vazifalar roster: open the student's
        latest submission (files, izoh, previous attempts) AND the ball input
        in a single dialog, instead of drilling list -> submissions -> form."""
        self.ensure_one()
        return self.env["edu.homework.grade.wizard"].open_grading(
            student=self.student_id,
            homework=self.homework_id,
            report=self,
        )

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