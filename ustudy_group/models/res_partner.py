from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import AccessError

from .edu_group import edu_admin_locked


class ResPartner(models.Model):
    _inherit = "res.partner"

    def unlink(self):
        # TZ (Administrator roli): contacts are never deleted — the whole
        # student history (enrollments, attendance, payments) hangs off the
        # partner. Archiving (active=False) is the only removal.
        if edu_admin_locked(self.env):
            raise AccessError(_(
                "Administrator kontaktni o'chira olmaydi — faqat arxivlash "
                "(Archive) mumkin."
            ))
        return super().unlink()

    group_student_ids = fields.One2many(
        "edu.group.student",
        "student_id",
        string="Groups",
    )

    group_count = fields.Integer(
        string="Groups",
        compute="_compute_group_count",
        store=False,
    )

    def _compute_group_count(self):
        for partner in self:
            partner.group_count = len(partner.group_student_ids)

    def action_view_groups(self):
        """Smart button: open groups that contain this student."""
        self.ensure_one()
        action = self.env.ref("ustudy_group.action_edu_group_list").read()[0]
        # only groups where this partner is in student_line_ids
        action["domain"] = [("student_line_ids.student_id", "=", self.id)]
        action["context"] = dict(self.env.context or {}, default_student_id=self.id)
        return action

    # ----------------------------------------------------------------
    # Aggregate fields for the Talabalar list view.
    # A student in multiple groups still shows as a single row; the
    # values aggregate across their non-cancelled enrollments so the
    # "O'quvchilar" layout (module / passed / amount / davomati) works
    # at the partner level.
    # ----------------------------------------------------------------
    current_module_summary = fields.Char(
        string="Joriy modul",
        compute="_compute_aggregate_group_info",
        store=False,
    )

    passed_lessons_total = fields.Integer(
        string="O'tilingan darslar",
        compute="_compute_aggregate_group_info",
        store=False,
    )

    passed_lessons_amount_total = fields.Float(
        string="O'tilgan darslar summasi",
        compute="_compute_aggregate_group_info",
        store=False,
    )

    student_status_summary = fields.Char(
        string="Status",
        compute="_compute_aggregate_group_info",
        store=False,
    )

    davomat_summary = fields.Char(
        string="Davomati",
        compute="_compute_aggregate_group_info",
        store=False,
    )

    student_balance = fields.Float(
        string="O'quvchi balans",
        compute="_compute_student_balance",
        store=False,
        readonly=True,
        help="Mirrors res.partner.finance_balance (defined in edu_finance, "
             "which depends on ustudy_group — we can't reference it in views "
             "loaded before edu_finance, so we expose it through a safe "
             "computed field here).",
    )

    def _compute_student_balance(self):
        has_field = "finance_balance" in self.env["res.partner"]._fields
        for partner in self:
            partner.student_balance = partner.finance_balance if has_field else 0.0

    # ----------------------------------------------------------------
    # Primary-enrollment columns for the Talabalar list view.
    # One row per student; per-group values come from the student's
    # "primary" enrollment = the most recently joined active enrollment
    # (falling back to the latest non-cancelled one). A student in
    # several groups therefore shows their current/active group here;
    # the full breakdown stays on the form's "Guruhlar" tab.
    # ----------------------------------------------------------------
    roster_group_id = fields.Many2one(
        "edu.group", string="Guruhi",
        compute="_compute_primary_enrollment", store=False,
        search="_search_roster_group_id",
    )
    roster_direction_id = fields.Many2one(
        "edu.course", string="Yo'nalish",
        compute="_compute_primary_enrollment", store=False,
        search="_search_roster_direction_id",
    )
    roster_teacher_id = fields.Many2one(
        "hr.employee", string="Ustozi",
        compute="_compute_primary_enrollment", store=False,
        search="_search_roster_teacher_id",
    )
    roster_course_start_date = fields.Date(
        string="Kurs boshlangan sana",
        compute="_compute_primary_enrollment", store=False,
        search="_search_roster_course_start_date",
    )
    roster_course_end_date = fields.Date(
        string="Kurs tugash sanasi",
        compute="_compute_primary_enrollment", store=False,
    )
    roster_current_module_id = fields.Many2one(
        "edu.module", string="Joriy modul",
        compute="_compute_primary_enrollment", store=False,
    )
    roster_current_lesson_no = fields.Integer(
        string="Joriy dars",
        compute="_compute_primary_enrollment", store=False,
    )
    roster_paid_lessons = fields.Integer(
        string="To'langan darslar soni",
        compute="_compute_primary_enrollment", store=False,
    )
    roster_lesson_balance = fields.Integer(
        string="To'lov statusi",
        compute="_compute_primary_enrollment", store=False,
        help="Signed lesson balance of the active enrollment: paid lessons "
             "minus passed lessons. Negative => qarzdor, positive => haqdor.",
    )
    roster_payment_health = fields.Selection(
        [("debtor", "Qarzdor"), ("paid", "Haqdor")],
        string="To'lov holati",
        compute="_compute_primary_enrollment", store=False,
        search="_search_roster_payment_health",
    )

    # Stored copies of the primary group/course, for the Talabalar search
    # panel (click-to-filter sidebar): the panel groups and counts records,
    # which needs real columns. The non-stored roster_* twins above keep
    # their any-enrollment search semantics for the search box.
    primary_group_id = fields.Many2one(
        "edu.group", string="Guruh",
        compute="_compute_primary_enrollment", store=True,
    )
    primary_course_id = fields.Many2one(
        "edu.course", string="Yo'nalish",
        compute="_compute_primary_enrollment", store=True,
    )

    # ----------------------------------------------------------------
    # Search helpers. The roster_* columns are non-stored computed
    # fields, so the Talabalar search view can't filter on them out of
    # the box. Group / teacher / course / start-date filters delegate to
    # the stored enrollment relation (group_student_ids), so a student
    # matches when ANY of their enrollments matches. Payment health has
    # no stored backing, so it is computed per student and matched in
    # Python.
    # ----------------------------------------------------------------
    def _search_roster_group_id(self, operator, value):
        return [("group_student_ids.group_id", operator, value)]

    def _search_roster_teacher_id(self, operator, value):
        return [("group_student_ids.group_id.teacher_id", operator, value)]

    def _search_roster_direction_id(self, operator, value):
        return [("group_student_ids.group_id.course_id", operator, value)]

    def _search_roster_course_start_date(self, operator, value):
        return [("group_student_ids.group_id.start_date", operator, value)]

    def _search_roster_payment_health(self, operator, value):
        # Odoo 19 normalizes '=' to 'in' and passes the value as an OrderedSet
        # (not list/tuple), so unpack any non-string iterable.
        if isinstance(value, str) or not hasattr(value, "__iter__"):
            targets = {value}
        else:
            targets = set(value)
        students = self.search([("is_student", "=", True)])
        if operator in ("=", "in"):
            matched = students.filtered(lambda s: s.roster_payment_health in targets)
        elif operator in ("!=", "not in"):
            matched = students.filtered(lambda s: s.roster_payment_health not in targets)
        else:
            return [("id", "=", False)]
        return [("id", "in", matched.ids)]

    @api.depends(
        "group_student_ids",
        "group_student_ids.state",
        "group_student_ids.enrollment_date",
        "group_student_ids.group_id",
        "group_student_ids.current_module_id",
        "group_student_ids.lessons_in_current_module",
        "group_student_ids.paid_lessons_count",
        "group_student_ids.passed_lessons_count",
    )
    def _compute_primary_enrollment(self):
        # Warm the caches in batch before the loop. filtered()/sorted()[:1]
        # below shrink the prefetch set to one record, so accessing the
        # computed line fields inside the loop would recompute them one line
        # at a time (2-3 SQL queries per line — the old "Qarzdor/Haqdor
        # filter takes seconds" bug). One mapped() call on the full
        # recordset computes every line/group in a single batch instead.
        all_lines = self.group_student_ids
        all_lines.mapped("payment_health")  # + lesson_balance, paid/passed counts
        all_groups = all_lines.group_id
        all_groups.mapped("course_id")  # fetches all group columns at once

        for partner in self:
            lines = partner.group_student_ids.filtered(lambda l: l.state != "cancelled")
            pool = lines.filtered(lambda l: l.state == "active") or lines
            line = pool.sorted(
                key=lambda l: l.enrollment_date or date.min, reverse=True
            )[:1]

            group = line.group_id
            partner.roster_group_id = group.id
            partner.roster_direction_id = group.course_id.id
            partner.primary_group_id = group.id
            partner.primary_course_id = group.course_id.id
            partner.roster_teacher_id = group.teacher_id.id
            partner.roster_course_start_date = group.start_date
            partner.roster_course_end_date = group.end_date
            partner.roster_current_module_id = line.current_module_id.id
            partner.roster_current_lesson_no = line.lessons_in_current_module
            partner.roster_paid_lessons = line.paid_lessons_count
            partner.roster_lesson_balance = line.lesson_balance
            partner.roster_payment_health = line.payment_health or False

    @api.depends(
        "group_student_ids",
        "group_student_ids.state",
        "group_student_ids.current_module_id",
        "group_student_ids.passed_lessons_count",
        "group_student_ids.passed_lessons_amount",
        "group_student_ids.attended_lessons_count",
    )
    def _compute_aggregate_group_info(self):
        # Batch-compute the expensive line fields up front (see the same
        # warm-up in _compute_primary_enrollment for why).
        all_lines = self.group_student_ids
        all_lines.mapped("passed_lessons_count")
        all_lines.mapped("attended_lessons_count")

        for partner in self:
            # All non-cancelled enrollments — these "represent" the student.
            lines = partner.group_student_ids.filtered(
                lambda l: l.state != "cancelled"
            )

            active = lines.filtered(lambda l: l.state == "active")

            # Joriy modul: unique active module names joined with comma.
            modules = active.mapped("current_module_id.name")
            partner.current_module_summary = ", ".join(sorted(set(filter(None, modules)))) or ""

            # Lesson aggregates: sum across active enrollments.
            partner.passed_lessons_total = sum(active.mapped("passed_lessons_count"))
            partner.passed_lessons_amount_total = sum(active.mapped("passed_lessons_amount"))

            # Davomati: total attended / total passed across active enrollments.
            attended_sum = sum(active.mapped("attended_lessons_count"))
            passed_sum = partner.passed_lessons_total
            partner.davomat_summary = f"{attended_sum}/{passed_sum}"

            # Status:
            #  - "Faol (N)" if any line is active (N = active count)
            #  - else "Muzlatilgan" if any frozen
            #  - else "Tugatgan" if any completed
            #  - else empty
            if active:
                partner.student_status_summary = f"Faol ({len(active)})"
            elif lines.filtered(lambda l: l.state == "frozen"):
                partner.student_status_summary = "Muzlatilgan"
            elif lines.filtered(lambda l: l.state == "completed"):
                partner.student_status_summary = "Tugatgan"
            else:
                partner.student_status_summary = ""
