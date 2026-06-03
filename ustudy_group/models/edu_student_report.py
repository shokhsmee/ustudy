from odoo import fields, models


class EduStudentLessonReport(models.Model):
    """
    SQL view: one row per (student, timetable_entry).
    """
    _name = "edu.group.student.lesson.report"
    _description = "Student Lesson Report (Timeline)"
    _auto = False
    _order = "start_datetime"
    _rec_name = "display_name"

    # Must match exactly what's in the SQL SELECT
    attendance_label = fields.Char(string="Label", readonly=True)

    timetable_id = fields.Many2one("edu.timetable", string="Lesson", readonly=True)
    group_id = fields.Many2one("edu.group", string="Group", readonly=True)
    teacher_id = fields.Many2one("hr.employee", string="Teacher", readonly=True)
    timetable_state = fields.Selection([
        ("scheduled",   "Scheduled"),
        ("in_progress", "In Progress"),
        ("completed",   "Completed"),
        ("cancelled",   "Cancelled"),
    ], string="Lesson Status", readonly=True)

    start_datetime = fields.Datetime(string="Start", readonly=True)
    end_datetime   = fields.Datetime(string="End",   readonly=True)

    student_id = fields.Many2one("res.partner", string="Student", readonly=True)

    attendance_status = fields.Selection([
        ("present",     "Keldi"),
        ("absent",      "Kelmadi"),
        ("not_started", "Boshlanmagan"),
    ], string="Attendance", readonly=True)

    company_id = fields.Many2one("res.company", string="Company", readonly=True)

    
    display_name = fields.Char(string="Display Name", readonly=True)
    
    
    def init(self):
        self.env.cr.execute("""
            DROP VIEW IF EXISTS edu_group_student_lesson_report CASCADE
        """)

        self.env.cr.execute("""
            CREATE VIEW edu_group_student_lesson_report AS
                SELECT
                    (tt.id * 100000 + gs.student_id) AS id,

                    tt.id AS timetable_id,
                    tt.group_id,
                    tt.teacher_id,
                    tt.state AS timetable_state,
                    tt.start_datetime,
                    tt.end_datetime,
                    gs.student_id,

                    COALESCE(al.status, 'not_started') AS attendance_status,

                    CASE COALESCE(al.status, 'not_started')
                        WHEN 'present' THEN '✅ Keldi'
                        WHEN 'absent' THEN '❌ Kelmadi'
                        ELSE '🔵 Boshlanmagan'
                    END AS attendance_label,

                    rp.name || ' - ' ||
                    CASE COALESCE(al.status,'not_started')
                        WHEN 'present' THEN '✅ Keldi'
                        WHEN 'absent' THEN '❌ Kelmadi'
                        ELSE '🔵 Boshlanmagan'
                    END AS display_name,

                    tt.company_id

                FROM edu_timetable tt

                JOIN edu_group_student gs
                    ON gs.group_id = tt.group_id
                    AND gs.state != 'cancelled'
                    AND (
                        gs.enrollment_date IS NULL
                        OR tt.start_datetime >= gs.enrollment_date::timestamp
                    )

                JOIN res_partner rp
                    ON rp.id = gs.student_id

                LEFT JOIN edu_attendance ea
                    ON ea.timetable_id = tt.id

                LEFT JOIN edu_attendance_line al
                    ON al.attendance_id = ea.id
                    AND al.student_id = gs.student_id

                WHERE tt.state != 'cancelled'
        """)