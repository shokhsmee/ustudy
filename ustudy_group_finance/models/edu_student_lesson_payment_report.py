from odoo import api, fields, models, tools
from odoo.tools.sql import table_exists


class EduStudentLessonPaymentReport(models.Model):
    _name = "edu.student.lesson.payment.report"
    _description = "Student Lesson Payment Report"
    _auto = False
    _rec_name = "timetable_name"
    _order = "start_datetime asc, timetable_id asc"

    student_id = fields.Many2one("res.partner", string="Student", readonly=True)
    timetable_id = fields.Many2one("edu.timetable", string="Dars", readonly=True)
    timetable_name = fields.Char(string="Dars nomi", readonly=True)
    group_id = fields.Many2one("edu.group", string="Guruh", readonly=True)
    start_datetime = fields.Datetime(string="Boshlash vaqti", readonly=True)
    end_datetime = fields.Datetime(string="Tugash vaqti", readonly=True)
    timetable_state = fields.Selection(
        [
            ("scheduled", "Rejalashtirilgan"),
            ("in_progress", "Jarayonda"),
            ("completed", "Yakunlangan"),
            ("cancelled", "Bekor qilingan"),
        ],
        string="Dars holati",
        readonly=True,
    )
    lesson_rank = fields.Integer(string="Dars #", readonly=True)
    total_paid = fields.Float(string="Jami to'langan", readonly=True)
    per_lesson = fields.Float(string="Dars narxi", readonly=True)
    paid_lessons = fields.Integer(string="To'langan darslar", readonly=True)
    payment_status = fields.Selection(
        [
            ("paid", "To'liq to'langan"),
            ("partial", "Qisman to'langan"),
            ("not_paid", "To'lanmagan"),
        ],
        string="To'lov holati",
        readonly=True,
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)

        # Per-module discounts count as covered (paid) amount once the
        # student has reached that module. Guarded: on a fresh install this
        # view's init can run before the discount table exists.
        has_discounts = table_exists(self.env.cr, "edu_student_module_discount")
        discount_cte = """,
                student_discounts AS (
                    SELECT
                        gs.student_id,
                        COALESCE(SUM(d.discount_amount), 0.0) AS total_discount
                    FROM edu_student_module_discount d
                    JOIN edu_group_student gs ON gs.id = d.student_line_id
                    JOIN edu_module m ON m.id = d.module_id
                    LEFT JOIN edu_module cm ON cm.id = gs.current_module_id
                    WHERE m.sequence <= COALESCE(cm.sequence, m.sequence)
                    GROUP BY gs.student_id
                )""" if has_discounts else ""
        total_paid_expr = (
            "COALESCE(sp.total_paid, 0.0) + COALESCE(sd.total_discount, 0.0)"
            if has_discounts else "COALESCE(sp.total_paid, 0.0)"
        )
        discount_join = (
            "LEFT JOIN student_discounts sd ON sd.student_id = gs.student_id"
            if has_discounts else ""
        )

        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH company_config AS (
                    -- one config per company (latest by id)
                    SELECT DISTINCT ON (company_id)
                        company_id,
                        module_price,
                        lessons_per_module
                    FROM edu_config
                    ORDER BY company_id, id DESC
                ),
                student_payments AS (
                    SELECT
                        cf.partner_id,
                        COALESCE(SUM(cf.amount), 0.0) AS total_paid
                    FROM cc_finance cf
                    JOIN cc_payment_type cpt ON cpt.id = cf.payment_type_id
                    WHERE cpt.code = 'student_module'
                      AND cf.transaction_type = 'income'
                      AND cf.state = 'confirmed'
                    GROUP BY cf.partner_id
                ){discount_cte},
                base AS (
                    SELECT
                        gs.student_id,
                        tt.id AS timetable_id,
                        tt.name AS timetable_name,
                        tt.group_id,
                        tt.start_datetime,
                        COALESCE(tt.end_datetime, tt.start_datetime + INTERVAL '90 minutes') AS end_datetime,
                        tt.state AS timetable_state,
                        {total_paid_expr} AS total_paid,
                        ROW_NUMBER() OVER (
                            PARTITION BY gs.student_id
                            ORDER BY tt.start_datetime ASC, tt.id ASC
                        ) AS lesson_rank,
                        CASE
                            WHEN COALESCE(cfg.lessons_per_module, 0) > 0
                            THEN cfg.module_price / cfg.lessons_per_module
                            ELSE 0.0
                        END AS per_lesson
                    FROM edu_group_student gs
                    JOIN edu_timetable tt
                        ON tt.group_id = gs.group_id
                        AND tt.state != 'cancelled'
                    LEFT JOIN student_payments sp ON sp.partner_id = gs.student_id
                    {discount_join}
                    LEFT JOIN company_config cfg ON cfg.company_id = gs.company_id
                )
                SELECT
                    ROW_NUMBER() OVER (
                        ORDER BY start_datetime ASC, timetable_id ASC, student_id
                    ) AS id,
                    student_id,
                    timetable_id,
                    timetable_name,
                    group_id,
                    start_datetime,
                    end_datetime,
                    timetable_state,
                    total_paid,
                    lesson_rank,
                    per_lesson,
                    CASE
                        WHEN per_lesson > 0
                        THEN FLOOR(total_paid / per_lesson)::int
                        ELSE 0
                    END AS paid_lessons,
                    CASE
                        WHEN per_lesson > 0
                             AND lesson_rank <= FLOOR(total_paid / per_lesson)::int
                             THEN 'paid'
                        WHEN per_lesson > 0
                             AND lesson_rank = FLOOR(total_paid / per_lesson)::int + 1
                             AND (total_paid - FLOOR(total_paid / per_lesson) * per_lesson) > 0.01
                             THEN 'partial'
                        ELSE 'not_paid'
                    END AS payment_status
                FROM base
            )
        """)

    @api.model
    def get_payment_dashboard(self, student_id=False):
        if not student_id:
            return {"total_paid": 0, "paid_lessons": 0, "debt_lessons": 0, "payment_foizi": "0%"}

        records = self.search([("student_id", "=", student_id)])
        if not records:
            return {"total_paid": 0, "paid_lessons": 0, "debt_lessons": 0, "payment_foizi": "0%"}

        total_lessons = len(records)
        total_paid = records[0].total_paid
        per_lesson = records[0].per_lesson
        paid_lessons = records[0].paid_lessons

        debt_lessons = max(0, total_lessons - paid_lessons)
        total_cost = total_lessons * per_lesson
        percent = round(total_paid / total_cost * 100) if total_cost > 0 else 0
        percent = min(percent, 100)

        def fmt(amount):
            return f"{amount:,.0f}".replace(",", " ")

        return {
            "total_paid": fmt(total_paid),
            "paid_lessons": paid_lessons,
            "debt_lessons": debt_lessons,
            "payment_foizi": f"{percent}%",
        }
