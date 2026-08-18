from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from datetime import timedelta


def teacher_locked(env):
    """Teachers may only run the attendance flow; scheduling and group
    administration stay admin-only (system admins and the Administrator
    role both count as administration). sudo'd flows are never locked."""
    return (
        not env.su
        and env.user.has_group("ustudy_group.group_teacher")
        and not env.user.has_group("base.group_system")
        and not env.user.has_group("ustudy_group.group_edu_admin")
    )


def edu_administration(env):
    """Users acting as administration in the attendance flow (confirm
    without a photo, reset a confirmed attendance): system admins and the
    operational Administrator role."""
    return env.user.has_group("base.group_system") or env.user.has_group(
        "ustudy_group.group_edu_admin"
    )


def edu_admin_locked(env):
    """The Administrator role (TZ) manages students, groups, schedule, CRM
    and events — but never deletes contacts and never touches payment
    records. sudo'd flows and system admins are never locked."""
    return (
        not env.su
        and env.user.has_group("ustudy_group.group_edu_admin")
        and not env.user.has_group("base.group_system")
    )


class EduGroup(models.Model):
    _name = "edu.group"
    _description = "Student Group"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(string="Group Name", required=True, tracking=True)

    course_id = fields.Many2one(
        "edu.course",
        string="Course",
        required=True,
        tracking=True,
        ondelete="restrict",
        domain="[('company_id','=',company_id)]"
    )
    
    homework_timetable_count = fields.Integer(
        compute="_compute_homework_timetable_count",
        store=False,
    )

    def _compute_homework_timetable_count(self):
        for g in self:
            # store bo‘lmagani uchun python filter
            g.homework_timetable_count = len(g.timetable_ids.filtered(lambda t: t.has_homework))

    def action_view_group_homeworks(self):
        self.ensure_one()
        # domain bilan filtrlab bo'lmaydi (has_homework store=False),
        # shuning uchun timetable listni ochib beradi,
        # list viewda esa search filter qo‘shamiz (keyingi xml)
        return {
            "name": "Topshiriqlar - %s" % self.name,
            "type": "ir.actions.act_window",
            "res_model": "edu.timetable",
            "view_mode": "list,form",
            "domain": [("group_id", "=", self.id)],
            "context": {"search_default_has_homework": 1},
        }


    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True
    )

    slide_channel_id = fields.Many2one(
        "slide.channel",
        string="eLearning Course",
        related="course_id.slide_channel_id",
        store=True,
        readonly=True,
    )

    group_color = fields.Integer(string="Color", default=0)

    course_count = fields.Integer(
        string="Darslar soni",
        tracking=True,
        compute="_compute_group_lesson_count",
    )

    teacher_id = fields.Many2one(
        "hr.employee",
        string="Teacher",
        tracking=True,
        ondelete="set null",
    )
    extra_teacher_id = fields.Many2one(
        "hr.employee",
        string="Mentor",
        tracking=True,
        ondelete="set null",
    )

    start_date = fields.Date(string="Start Date", tracking=True)
    end_date = fields.Date(string="End Date", tracking=True)

    lesson_start = fields.Float(string="Lesson start", tracking=True)
    lesson_end = fields.Float(string="Lesson end", tracking=True)
    lesson_count = fields.Integer(string="Lesson Count", default=0, tracking=True)
    use_lesson_count = fields.Boolean(string="Use lesson count", default=True)
    start_lesson_number = fields.Integer(
        string="Start from Lesson",
        default=1,
        tracking=True,
        help="Lesson number this group starts from (e.g. 40 means the group begins at slide 40 of the course)",
    )
    
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("running", "Running"),
            ("done", "Finished"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        tracking=True,
    )

    student_line_ids = fields.One2many(
        "edu.group.student",
        "group_id",
        string="Students",
    )

    # Same inverse as student_line_ids, split by state via a domain baked into
    # the FIELD definition (a view-level domain on a one2many does not reliably
    # filter displayed rows, so we use dedicated fields instead):
    #   active_student_line_ids    -> the working roster (everything but removed)
    #   cancelled_student_line_ids -> removed / Guruhdan chetlatilgan students
    active_student_line_ids = fields.One2many(
        "edu.group.student",
        "group_id",
        string="O'quvchilar",
        domain=[("state", "!=", "cancelled")],
    )
    cancelled_student_line_ids = fields.One2many(
        "edu.group.student",
        "group_id",
        string="Guruhdan chetlatilganlar",
        domain=[("state", "=", "cancelled")],
    )

    student_count = fields.Integer(
        string="Students",
        compute="_compute_student_count",
        store=False,
    )

    cancelled_student_count = fields.Integer(
        string="Chetlatilgan o'quvchilar",
        compute="_compute_student_count",
        store=False,
    )

    # ------------------------------------------------------------------
    # Mini-dashboard KPIs (shown as cards at the top of the group form).
    # All non-stored / display-only. Homework % is soft-guarded because
    # vazifa_ratio is contributed by the optional ustudy_homework module.
    # ------------------------------------------------------------------
    active_student_count = fields.Integer(
        string="Aktiv o'quvchilar",
        compute="_compute_group_kpis",
        store=False,
    )
    stopped_student_count = fields.Integer(
        string="To'xtatgan o'quvchilar",
        compute="_compute_group_kpis",
        store=False,
    )
    attendance_display = fields.Char(
        string="Davomat",
        compute="_compute_group_kpis",
        store=False,
    )
    homework_display = fields.Char(
        string="Vazifa ko'rsatkichi",
        compute="_compute_group_kpis",
        store=False,
    )
    debt_total_display = fields.Char(
        string="Qarzdorlar jami",
        compute="_compute_group_kpis",
        store=False,
    )

    @api.depends("student_line_ids", "student_line_ids.state")
    def _compute_group_kpis(self):
        config = self.env["edu.config"].get_config()
        lpm = config.lessons_per_module or 12
        per_lesson = (config.module_price / lpm) if lpm else 0.0
        has_homework = "vazifa_ratio" in self.env["edu.group.student"]._fields

        for rec in self:
            lines = rec.student_line_ids
            active = lines.filtered(lambda l: l.state == "active")
            stopped = lines.filtered(lambda l: l.state in ("frozen", "cancelled"))

            rec.active_student_count = len(active)
            rec.stopped_student_count = len(stopped)

            # Davomat: attended / passed lessons across active students.
            passed = sum(active.mapped("passed_lessons_count"))
            attended = sum(active.mapped("attended_lessons_count"))
            rec.attendance_display = ("%d%%" % round(attended * 100.0 / passed)) if passed else "0%"

            # Vazifa ko'rsatkichi: submitted / total homeworks (ustudy_homework only).
            if has_homework and active:
                submitted = total = 0
                for line in active:
                    try:
                        s, t = (line.vazifa_ratio or "0/0").split("/")
                        submitted += int(s)
                        total += int(t)
                    except (ValueError, AttributeError):
                        continue
                rec.homework_display = ("%d%%" % round(submitted * 100.0 / total)) if total else "0%"
            else:
                rec.homework_display = "0%"

            # Qarzdorlar jami: owed lessons x per-lesson price across non-cancelled students.
            owed = sum(lines.filtered(lambda l: l.state != "cancelled").mapped("debt_lessons_count"))
            rec.debt_total_display = "{:,.0f}".format(owed * per_lesson).replace(",", " ")

    lesson_days = fields.Many2many(
        'edu.weekday',
        string='Lesson Days',
    )

    lesson_room = fields.Many2one(
        "edu.room",
        string="Lesson Room",
        ondelete="set null",
        tracking=True,
        # archived rooms are invisible on the board/bandlik views — lessons
        # generated into one silently vanish there (2026-07-31 room cleanup
        # left groups pointing at archived duplicates like "1 Xona")
        domain=[("active", "=", True)],
    )

    notes = fields.Text(string="Notes")
    active = fields.Boolean(default=True)

    # UI flag for the views: True when the current user is a locked teacher,
    # so admin fields render readonly. Enforcement is in write()/create().
    teacher_readonly = fields.Boolean(compute="_compute_teacher_readonly")

    def _compute_teacher_readonly(self):
        locked = teacher_locked(self.env)
        for rec in self:
            rec.teacher_readonly = locked


    started_lessons_count = fields.Integer(
        string="Started Lessons",
        compute="_compute_started_lessons_count",
        store=False
    )

    is_at_module_start = fields.Boolean(
        string="At Module Boundary",
        compute="_compute_module_boundary",
        store=False,
        help="True when the group is positioned at the 1st lesson of any module "
             "(i.e. (start_lesson_number - 1 + started_lessons_count) is a multiple of lessons_per_module). "
             "Used to restrict mid-group student enrollment to clean module boundaries.",
    )

    lessons_until_next_module = fields.Integer(
        string="Lessons Until Next Module",
        compute="_compute_module_boundary",
        store=False,
        help="How many more lessons must be completed before the group reaches the next module boundary. "
             "0 means the group is currently AT a boundary (next lesson starts a new module).",
    )

    lessons_into_current_module = fields.Integer(
        string="Lessons Done in Current Module",
        compute="_compute_module_boundary",
        store=False,
        help="How many lessons of the current module the group has already started/completed.",
    )

    max_join_lesson = fields.Integer(
        string="Join Deadline (Lesson #)",
        compute="_compute_module_boundary",
        store=False,
        help="Config value: new students may join only within the first N lessons of the module.",
    )

    can_add_student_now = fields.Boolean(
        string="Can Add Student Now",
        compute="_compute_module_boundary",
        store=False,
        help="True while the group is within the first max_join_lesson lessons of its current module, "
             "so a new student can still join it.",
    )

    @api.depends("timetable_ids.state")
    def _compute_started_lessons_count(self):
        for rec in self:
            started = rec.timetable_ids.filtered(lambda t: t.state in ["in_progress", "completed"])
            rec.started_lessons_count = len(started)

    @api.depends("timetable_ids.state", "start_lesson_number")
    def _compute_module_boundary(self):
        config = self.env["edu.config"].get_config()
        lpm = config.lessons_per_module or 12
        mjl = config.max_join_lesson or 4
        for rec in self:
            started = len(rec.timetable_ids.filtered(lambda t: t.state in ["in_progress", "completed"]))
            course_offset = (rec.start_lesson_number or 1) - 1 + started
            position = course_offset % lpm
            rec.is_at_module_start = (position == 0)
            rec.lessons_until_next_module = 0 if position == 0 else (lpm - position)
            rec.lessons_into_current_module = position
            rec.max_join_lesson = mjl
            rec.can_add_student_now = (position < mjl)


    @api.onchange("start_date", "lesson_days", "lesson_count", "use_lesson_count")
    def _onchange_end_date_from_count(self):
        for rec in self:
            if not rec.use_lesson_count:
                continue
            if not rec.start_date or not rec.lesson_days or not rec.lesson_count:
                continue

            allowed = set(rec.lesson_days.mapped("sequence"))
            d = rec.start_date
            lessons = 0

            while lessons < rec.lesson_count:
                weekday_seq = d.weekday() + 1
                if weekday_seq in allowed:
                    lessons += 1
                    if lessons == rec.lesson_count:
                        rec.end_date = d
                        break
                d += timedelta(days=1)

    @api.model
    def get_group_dashboard(self):
        total = self.search_count([])
        active = self.search_count([('state', '=', 'running')])

        student_count = self.env['edu.group.student'].search_count([
            ('group_id.active', '=', True),
        ])

        active_student_count = self.env['edu.group.student'].search_count([
            ('state', '=', 'active'),
            ('group_id.state', '=', 'running'),
            ('group_id.active', '=', True),
        ])

        return {
            'total': total,
            'active': active,
            'students': student_count,
            'active_students': active_student_count,
        }

    @api.depends("student_line_ids")
    @api.depends("student_line_ids", "student_line_ids.state")
    def _compute_student_count(self):
        for group in self:
            group.student_count = len(group.student_line_ids)
            group.cancelled_student_count = len(
                group.student_line_ids.filtered(lambda l: l.state == "cancelled")
            )

    @api.depends("timetable_ids.slide_id", "timetable_ids.state")
    def _compute_group_lesson_count(self):
        """Darslar = lessons actually scheduled for this group: distinct slides
        carried by its active (non-cancelled) timetable entries. Because the
        timetable is generated from start_lesson_number ("boshlangan dars"),
        this naturally counts only lessons from that starting lesson onward."""
        for group in self:
            active = group.timetable_ids.filtered(
                lambda t: t.slide_id and t.state != "cancelled"
            )
            group.course_count = len(active.mapped("slide_id"))

    def action_view_students(self):
        """Open students in this group"""
        self.ensure_one()
        return {
            'name': _('Students - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'edu.group.student',
            'view_mode': 'list,form',
            'domain': [('group_id', '=', self.id)],
            'context': {'default_group_id': self.id},
        }

    def action_view_lessons(self):
        """Open the lessons actually scheduled for this group: the slides carried
        by its active (non-cancelled) timetable entries, from boshlangan dars on.
        Matches the course_count ("Darslar") stat."""
        self.ensure_one()
        if self.slide_channel_id:
            slide_ids = self.timetable_ids.filtered(
                lambda t: t.slide_id and t.state != "cancelled"
            ).mapped("slide_id").ids
            return {
                'name': _('Course Lessons - %s', self.slide_channel_id.name),
                'type': 'ir.actions.act_window',
                'res_model': 'slide.slide',
                'view_mode': 'list,form',
                'domain': [('id', 'in', slide_ids)],
                'context': {'default_channel_id': self.slide_channel_id.id},
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('No eLearning course linked to this group.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }

    def action_add_student_midgroup(self):
        """Open wizard to add a student to this running group from a specific date.

        Only allowed while the group is within the first max_join_lesson lessons
        of its current module (default: 4). The joiner is enrolled into the
        group's CURRENT module with the group's current lesson count, so their
        module/payment tracking stays in sync with the group.
        """
        self.ensure_one()
        if not self.can_add_student_now:
            raise UserError(_(
                "Bu guruhga hozir yangi o'quvchi qo'shib bo'lmaydi. "
                "Joriy modulda %(done)s ta dars o'tib bo'lgan — o'quvchini faqat "
                "modulning birinchi %(limit)s ta darsi ichida qo'shish mumkin. "
                "Keyingi modulgacha %(left)s ta dars qoldi."
            ) % {
                "done": self.lessons_into_current_module,
                "limit": self.max_join_lesson,
                "left": self.lessons_until_next_module,
            })
        return {
            'name': _("Guruhga O'quvchi Qo'shish"),
            'type': 'ir.actions.act_window',
            'res_model': 'edu.group.add.student.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_group_id': self.id,
            },
        }

    def _module_position_for_lesson(self, lesson_number):
        """Map a 1-based course lesson number to (edu.module, position_in_module).

        position_in_module = how many lessons of that module are already behind the
        given lesson (0 => the lesson starts a fresh module). Falls back to the first
        module when the computed sequence has no matching edu.module record."""
        self.ensure_one()
        config = self.env["edu.config"].get_config()
        lpm = config.lessons_per_module or 12
        course_offset = (lesson_number or 1) - 1
        module_seq = course_offset // lpm + 1
        position_in_module = course_offset % lpm
        module = self.env["edu.module"].search([("sequence", "=", module_seq)], limit=1)
        if not module:
            module = self.env["edu.module"].search([], order="sequence asc", limit=1)
        return module, position_in_module

    # NOTE: the group's single write() override lives next to the teacher
    # lock below — a second `def write` in this class would silently shadow
    # it (Python keeps only the last def), which is exactly the bug that had
    # disabled the start_lesson_number re-sync until 1.14.0.

    def _sync_students_starting_module(self):
        """Re-point student lines to the module implied by the group's start_lesson_number.

        Only touches lines still at their original starting module (current == starting),
        so groups already in progress don't lose per-student module advancement."""
        for group in self:
            module, position = group._module_position_for_lesson(group.start_lesson_number)
            if not module:
                continue
            lines = group.student_line_ids.filtered(
                lambda l: l.state != "cancelled"
                and (not l.current_module_id or l.current_module_id == l.starting_module_id)
            )
            for line in lines:
                line.write({
                    "current_module_id": module.id,
                    "starting_module_id": module.id,
                    "lessons_in_current_module": position if (group.start_lesson_number or 1) > 1 else 0,
                })

    def action_start(self):
        """Change state to running"""
        self.write({'state': 'running'})

    def action_complete(self):
        """Change state to done"""
        self.write({'state': 'done'})
    
    def action_running(self):
        """Restart course - change state back to running"""
        self.write({'state': 'running'})

    # Group administration is not the teacher's job: teachers keep read access
    # (record rule) and the chatter, but the fields that define the group and
    # its schedule are locked for them.
    TEACHER_PROTECTED_FIELDS = {
        "name", "course_id", "teacher_id", "extra_teacher_id", "lesson_room",
        "group_color", "start_date", "end_date", "lesson_start", "lesson_end",
        "lesson_count", "use_lesson_count", "start_lesson_number",
        "lesson_days", "lesson_start_time", "lesson_duration",
        "state", "active", "company_id",
    }

    @api.model_create_multi
    def create(self, vals_list):
        if teacher_locked(self.env):
            raise AccessError(_("O'qituvchi yangi guruh yarata olmaydi. Bu administratsiya vazifasi."))
        return super().create(vals_list)

    def write(self, vals):
        if teacher_locked(self.env):
            blocked = self.TEACHER_PROTECTED_FIELDS & set(vals)
            if blocked:
                raise AccessError(_(
                    "O'qituvchi guruh sozlamalarini o'zgartira olmaydi (%s). Bu administratsiya vazifasi.",
                    ", ".join(sorted(blocked)),
                ))
        res = super().write(vals)
        # When the group's starting lesson changes, its students' current module was
        # snapshotted at create-time from the OLD value and is now stale. Re-baseline
        # the students that haven't advanced past their starting module yet.
        if "start_lesson_number" in vals:
            self._sync_students_starting_module()
        # A finished course leaves the schedule: its not-yet-held lessons are
        # cancelled so they disappear from the timetable/board and stop holding
        # the room (the conflict check ignores cancelled entries). Held lessons
        # (in_progress/completed) keep their attendance history untouched.
        if vals.get("state") == "done":
            self.env["edu.timetable"].sudo().search([
                ("group_id", "in", self.ids),
                ("state", "=", "scheduled"),
            ]).write({"state": "cancelled"})
        return res


    attendance_count = fields.Integer(
        string="Attendance Count",
        compute="_compute_attendance_count",
        store=False,
    )


    def _compute_attendance_count(self):
        Report = self.env["edu.student.lesson.report"]
        for group in self:
            group.attendance_count = Report.search_count([
                ("group_id", "=", group.id),
                ("timetable_state", "in", ["in_progress", "completed"]),
            ])

    def action_view_group_attendance_timeline(self):
        """Open the attendance matrix (OWL grid replicating the Davomat
        Google Sheet): rows = students, columns = lessons per module, cells =
        Bor/Yo'q with per-lesson % and per-module summaries. Replaces the old
        OCA web_timeline view; method name kept so existing buttons/refs work.
        """
        self.ensure_one()
        return {
            "name": _("Davomat - %s") % self.name,
            "type": "ir.actions.client",
            "tag": "ustudy_group.davomat_matrix",
            "params": {"group_id": self.id},
            "context": {"group_id": self.id},
        }


class EduGroupStudent(models.Model):
    _name = "edu.group.student"
    _description = "Group Student"

    group_id = fields.Many2one(
        "edu.group",
        string="Group",
        required=True,
        ondelete="cascade",
        domain="[('company_id','=',company_id)]"
    )

    student_id = fields.Many2one(
        "res.partner",
        string="Student",
        required=True,
        domain="[('is_student', '=', True), ('company_id','=',company_id)]",
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True
    )

    student_name = fields.Char(
        string="Full Name",
        related="student_id.name",
        store=False,
    )
    total_courses = fields.Integer(
        string="Courses",
        related="student_id.total_courses",
        store=False,
    )

    @api.constrains("group_id", "student_id")
    def _check_unique_student_per_group(self):
        """A student may appear in a group only once. Guards every path
        (group form One2many, wizard, imports), not just the add wizard."""
        for rec in self:
            if not rec.group_id or not rec.student_id:
                continue
            duplicate = self.search_count([
                ("id", "!=", rec.id),
                ("group_id", "=", rec.group_id.id),
                ("student_id", "=", rec.student_id.id),
            ])
            if duplicate:
                raise ValidationError(_(
                    "%(student)s allaqachon %(group)s guruhida mavjud. "
                    "Bir o'quvchi bir guruhga faqat bir marta qo'shiladi.",
                    student=rec.student_id.name,
                    group=rec.group_id.name,
                ))

    # ---------------------------------------------------------------
    # Per-enrollment payment standing. Reused by res.partner to show the
    # student's active enrollment on the "Talabalar ro'yxati" list.
    # ---------------------------------------------------------------
    lesson_balance = fields.Integer(
        string="To'lov statusi",
        compute="_compute_lesson_balance",
        store=False,
        help="Signed lesson balance: paid lessons minus passed lessons. "
             "Negative => qarzdor, positive => haqdor.",
    )
    payment_health = fields.Selection(
        [
            ("debtor", "Qarzdor"),
            ("paid", "Haqdor"),
        ],
        string="To'lov holati",
        compute="_compute_lesson_balance",
        store=False,
        help="Qarzdor (qizil) when the student owes lessons, Haqdor (yashil) "
             "when paid lessons cover the passed lessons.",
    )

    @api.depends("paid_lessons_count", "passed_lessons_count")
    def _compute_lesson_balance(self):
        for rec in self:
            balance = rec.paid_lessons_count - rec.passed_lessons_count
            rec.lesson_balance = balance
            rec.payment_health = "debtor" if balance < 0 else "paid"

    # Module Payment Fields
    # current_module = fields.Integer(
    #     string="Current Module",
    #     default=1,
    #     help="Which module the student is currently in"
    # )
    current_module_id = fields.Many2one(
        "edu.module",
        string="Current Module",
        tracking=True
    )
    
    lessons_in_current_module = fields.Integer(
        string="Lessons in Module",
        default=0,
        help="Number of lessons attended in current module"
    )
    
    current_module_paid = fields.Boolean(
        string="Module Paid",
        default=False,
        help="Whether current module fee has been fully paid"
    )
    
    current_module_payment_amount = fields.Float(
        string="Amount Paid",
        default=0.0,
        help="Total amount paid for the current module"
    )
    
    module_price = fields.Float(
        string="Module Price",
        compute="_compute_module_price",
        help="Price from configuration"
    )
    
    payment_status = fields.Selection([
        ('not_started', 'Not Started'),
        ('partial', 'Partial Payment'),
        ('paid', 'Fully Paid'),
        ('overdue', 'Payment Overdue'),
    ], string="Payment Status", compute="_compute_payment_status", store=True)

    debt_status = fields.Selection(
        [
            ('paid', "Haqdor"),
            ('debtor', "Qarzdor"),
        ],
        string="To'lov holati",
        compute="_compute_debt_status",
        store=False,
    )

    @api.depends("passed_lessons_count", "paid_lessons_count")
    def _compute_debt_status(self):
        for rec in self:
            # Qarzdor only when passed (given) lessons exceed paid lessons.
            # When paid covers or equals passed lessons => haqdor.
            rec.debt_status = 'debtor' if rec.passed_lessons_count > rec.paid_lessons_count else 'paid'
    
    state = fields.Selection(
        [
            ("active", "Active"),
            ("completed", "Completed"),
            ("frozen", "Frozen"),
            ("cancelled", "Guruhdan chetlatilgan"),
        ],
        default="active",
    )

    enrollment_date = fields.Date(
        string="Enrollment Date",
        default=fields.Date.today,
        help="Date when student joined this group. Used to calculate attendance and module from that day.",
    )

    starting_module_id = fields.Many2one(
        "edu.module",
        string="Starting Module",
        readonly=True,
        copy=False,
        help="Module the student started from when they joined this group. "
             "Finance and lesson history before this module are hidden for mid-joiners.",
    )
    
    
    paid_amount_total = fields.Float(
        string="Paid Total",
        compute="_compute_paid_amount_total",
        store=False
    )

    paid_lessons_count = fields.Integer(
        string="Paid Lessons",
        compute="_compute_paid_lessons_count",
        store=False
    )

    attended_lessons_count = fields.Integer(
        string="Attended Lessons",
        compute="_compute_attended_lessons_count",
        store=False
    )

    # ---------------------------------------------------------------
    # New display fields for the group form's Students table layout.
    # See edu_group_views.xml (Students tab inside the group form).
    # ---------------------------------------------------------------
    passed_lessons_count = fields.Integer(
        string="O'tilingan darslar",
        compute="_compute_passed_lessons",
        store=False,
        help="Number of timetables in this group with state in_progress/completed "
             "since the student's enrollment_date.",
    )

    passed_lessons_amount = fields.Float(
        string="O'tilgan darslar summasi",
        compute="_compute_passed_lessons",
        store=False,
        help="passed_lessons_count × per-lesson price "
             "(module_price / lessons_per_module). The total cost of the lessons "
             "that have already happened for this student.",
    )

    debt_lessons_count = fields.Float(
        string="Qarz darslar",
        compute="_compute_debt_lessons",
        store=False,
        help="Difference between passed lessons and paid lessons, i.e. how many "
                "lessons the student owes payment for.",
    )
    
    
    student_balance = fields.Float(
        string="O'quvchi balans",
        compute="_compute_student_balance",
        store=False,
        readonly=True,
        help="Per-enrollment balance: sum of confirmed income payments minus "
             "expenses on cc.finance for this student_line_id. Scoped to this "
             "group only — does not aggregate across the student's other groups.",
    )

    davomat_ratio = fields.Char(
        string="Davomati",
        compute="_compute_davomat_ratio",
        store=False,
        help="Attendance since enrollment as 'present/passed'.",
    )
    
    
    def _compute_paid_amount_total(self):
        # Model-existence guard: during ustudy_group's own upgrade phase the
        # registry doesn't contain the finance models yet (they load later in
        # the module graph), and stored-field recomputes can reach this.
        if "cc.payment.type" not in self.env or "cc.finance" not in self.env:
            for rec in self:
                rec.paid_amount_total = 0.0
            return
        payment_type = self.env['cc.payment.type'].search([
            ('code', '=', 'student_module'),
            ('type_category', '=', 'student')
        ], limit=1)
        has_link = "student_line_id" in self.env["cc.finance"]._fields

        line_ids = [rec.id for rec in self if rec.id]
        if not payment_type or not has_link or not line_ids:
            for rec in self:
                rec.paid_amount_total = 0.0
            return

        # One query for the whole batch. The per-line starting-module scope
        # (see _get_module_scope_domain) is applied in Python from the
        # fetched module sequence, keeping the same semantics: records with
        # no module always count, others only from the starting module on.
        payments = self.env["cc.finance"].search_read(
            [
                ("student_line_id", "in", line_ids),
                ("payment_type_id", "=", payment_type.id),
                ("transaction_type", "=", "income"),
                ("state", "=", "confirmed"),
            ],
            ["student_line_id", "amount", "module_id"],
        )
        module_ids = list({p["module_id"][0] for p in payments if p["module_id"]})
        seq_by_module = {
            m["id"]: m["sequence"]
            for m in self.env["edu.module"].browse(module_ids).read(["sequence"])
        }
        payments_by_line = {}
        for p in payments:
            payments_by_line.setdefault(p["student_line_id"][0], []).append(p)

        for rec in self:
            rows = payments_by_line.get(rec.id) or ()
            min_seq = rec.starting_module_id.sequence if rec.starting_module_id else None
            total = 0.0
            for p in rows:
                if (
                    min_seq is not None
                    and p["module_id"]
                    and seq_by_module.get(p["module_id"][0], 0) < min_seq
                ):
                    continue
                total += p["amount"]
            rec.paid_amount_total = total

    def _get_module_scope_domain(self):
        """Return a cc.finance domain fragment limiting records to modules at or after
        the student's starting_module_id. Used everywhere finance is shown / summed
        for this student line so past modules don't appear and aren't billed."""
        self.ensure_one()
        if not self.starting_module_id:
            return []
        # Allow records with no module_id (general payments) and any record whose
        # module sequence is >= the student's starting module sequence.
        return [
            "|",
            ("module_id", "=", False),
            ("module_id.sequence", ">=", self.starting_module_id.sequence),
        ]
    
    
    def _compute_paid_lessons_count(self):
        config = self.env["edu.config"].get_config()

        for rec in self:
            if not config.lessons_per_module:
                rec.paid_lessons_count = 0
                continue

            per_lesson = config.module_price / config.lessons_per_module
            if per_lesson <= 0:
                rec.paid_lessons_count = 0
                continue

            rec.paid_lessons_count = int(rec.paid_amount_total // per_lesson)


    def _compute_attended_lessons_count(self):
        AttendanceLine = self.env["edu.attendance.line"]

        student_ids = list({rec.student_id.id for rec in self if rec.student_id})
        group_ids = list({rec.group_id.id for rec in self if rec.group_id})
        # One search for the whole batch; per-line enrollment_date cut-off is
        # applied in Python (attendance_date is a Date field).
        dates_by_pair = {}
        if student_ids and group_ids:
            lines = AttendanceLine.search([
                ("student_id", "in", student_ids),
                ("attendance_id.group_id", "in", group_ids),
                ("attendance_id.state", "=", "confirmed"),
                ("status", "=", "present"),
            ])
            for line in lines:
                key = (line.student_id.id, line.attendance_id.group_id.id)
                dates_by_pair.setdefault(key, []).append(
                    line.attendance_id.attendance_date
                )

        for rec in self:
            dates = dates_by_pair.get((rec.student_id.id, rec.group_id.id), ())
            if rec.enrollment_date:
                rec.attended_lessons_count = sum(
                    1 for d in dates if d and d >= rec.enrollment_date
                )
            else:
                rec.attended_lessons_count = len(dates)

    def _compute_passed_lessons(self):
        Timetable = self.env["edu.timetable"]
        config = self.env["edu.config"].get_config()
        lpm = config.lessons_per_module or 12
        per_lesson = (config.module_price / lpm) if lpm else 0.0

        group_ids = list({rec.group_id.id for rec in self if rec.group_id})
        # One query for all groups in the batch; the per-line
        # enrollment_date cut-off is applied in Python (both Date fields).
        dates_by_group = {}
        if group_ids:
            rows = Timetable.search_read(
                [
                    ("group_id", "in", group_ids),
                    ("state", "in", ["in_progress", "completed"]),
                ],
                ["group_id", "start_date"],
            )
            for row in rows:
                dates_by_group.setdefault(row["group_id"][0], []).append(
                    row["start_date"]
                )

        for rec in self:
            if not rec.group_id:
                rec.passed_lessons_count = 0
                rec.passed_lessons_amount = 0.0
                continue

            dates = dates_by_group.get(rec.group_id.id, ())
            if rec.enrollment_date:
                # Mirrors the SQL domain ("start_date", ">=", date): rows
                # with NULL start_date never match a >= comparison.
                count = sum(1 for d in dates if d and d >= rec.enrollment_date)
            else:
                count = len(dates)
            rec.passed_lessons_count = count
            rec.passed_lessons_amount = count * per_lesson


    def _compute_debt_lessons(self):
        for data in self:
            data.debt_lessons_count = max(0, data.passed_lessons_count - data.paid_lessons_count)

    def _compute_davomat_ratio(self):
        for rec in self:
            passed = rec.passed_lessons_count
            attended = rec.attended_lessons_count
            rec.davomat_ratio = f"{attended}/{passed}"

    def _compute_student_balance(self):
        # student_line_id was added on cc.finance by ustudy_group_finance. Guard so
        # this still computes (as 0) when that module isn't installed — and check
        # the model itself first: it is absent during ustudy_group's upgrade phase.
        has_link = (
            "cc.finance" in self.env
            and "student_line_id" in self.env["cc.finance"]._fields
        )
        line_ids = [rec.id for rec in self if rec.id]
        balances = {}
        if has_link and line_ids:
            rows = self.env["cc.finance"].search_read(
                [
                    ("student_line_id", "in", line_ids),
                    ("state", "=", "confirmed"),
                ],
                ["student_line_id", "amount", "transaction_type"],
            )
            for row in rows:
                line_id = row["student_line_id"][0]
                if row["transaction_type"] == "income":
                    balances[line_id] = balances.get(line_id, 0.0) + row["amount"]
                elif row["transaction_type"] == "expense":
                    balances[line_id] = balances.get(line_id, 0.0) - row["amount"]
        for rec in self:
            rec.student_balance = balances.get(rec.id, 0.0)

    
    finance_count = fields.Integer(
        compute="_compute_finance_count",
        string="Payments"
    )

    def _compute_finance_count(self):
        if "cc.payment.type" not in self.env or "cc.finance" not in self.env:
            for rec in self:
                rec.finance_count = 0
            return
        payment_type = self.env['cc.payment.type'].search([
            ('code', '=', 'student_module'),
            ('type_category', '=', 'student')
        ], limit=1)
        has_link = "student_line_id" in self.env["cc.finance"]._fields

        for rec in self:
            if not has_link or not rec.id:
                rec.finance_count = 0
                continue
            domain = [("student_line_id", "=", rec.id)]
            if payment_type:
                domain.append(("payment_type_id", "=", payment_type.id))
            domain += rec._get_module_scope_domain()

            rec.finance_count = self.env["cc.finance"].search_count(domain)


    def action_view_student_finance(self):
        self.ensure_one()

        payment_type = self.env['cc.payment.type'].search([
            ('code', '=', 'student_module'),
            ('type_category', '=', 'student')
        ], limit=1)

        has_link = "student_line_id" in self.env["cc.finance"]._fields
        if has_link:
            domain = [("student_line_id", "=", self.id)]
        else:
            domain = [("partner_id", "=", self.student_id.id)]
        if payment_type:
            domain.append(("payment_type_id", "=", payment_type.id))
        domain += self._get_module_scope_domain()

        view_id = self.env.ref("ustudy_group.view_cc_finance_student_module_list").id

        return {
            "name": _("Student Payments"),
            "type": "ir.actions.act_window",
            "res_model": "cc.finance",
            "view_mode": "list,form",
            "views": [(view_id, "list"), (False, "form")],
            "domain": domain,
            "context": {
                "default_partner_id": self.student_id.id,
                "default_student_line_id": self.id,
            }
        }

    
    @api.depends('lessons_in_current_module', 'current_module_paid', 'current_module_payment_amount')
    def _compute_payment_status(self):
        for record in self:
            config = self.env['edu.config'].get_config()
            
            if record.current_module_paid:
                record.payment_status = 'paid'
            elif record.current_module_payment_amount > 0:
                record.payment_status = 'partial'
            elif record.lessons_in_current_module >= config.full_payment_lesson:
                record.payment_status = 'overdue'
            else:
                record.payment_status = 'not_started'
    
    def _compute_module_price(self):
        config = self.env['edu.config'].get_config()
        for record in self:
            record.module_price = config.module_price
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            group = self.env['edu.group'].browse(vals['group_id']) if 'group_id' in vals else False

            if group and vals.get('company_id') is None:
                vals['company_id'] = group.company_id.id

            if not vals.get("current_module_id") and group:
                start_lesson = group.start_lesson_number or 1
                module, position_in_module = group._module_position_for_lesson(start_lesson)

                if module:
                    vals["current_module_id"] = module.id
                    # only pre-set position when group explicitly starts mid-course
                    if start_lesson > 1 and "lessons_in_current_module" not in vals:
                        vals["lessons_in_current_module"] = position_in_module

            # Always snapshot starting_module_id at create-time so finance/views can
            # filter past modules out for mid-joiners.
            if not vals.get("starting_module_id") and vals.get("current_module_id"):
                vals["starting_module_id"] = vals["current_module_id"]

        records = super().create(vals_list)
        records._enroll_in_course()
        return records

    def _enroll_in_course(self):
        """Auto-enroll the student into the group's eLearning course (slide.channel).

        Triggered whenever a student is added to a group (form or wizards both
        funnel through create). Idempotent: _action_add_members re-uses/unarchives
        any existing membership instead of creating a duplicate."""
        for rec in self:
            channel = rec.group_id.slide_channel_id
            partner = rec.student_id
            if not channel or not partner:
                continue
            memberships = channel.sudo()._action_add_members(partner)
            # Link the membership back to this group (only if not already tied to one).
            for cp in memberships.filtered(lambda m: not m.edu_group_id):
                cp.edu_group_id = rec.group_id.id

    
    def action_register_module_payment(self):
        self.ensure_one()

        config = self.env['edu.config'].get_config()

        if not self.current_module_id:
            raise UserError(_("Please set student module first!"))

        return {
            'name': _('Register Module Payment'),
            'type': 'ir.actions.act_window',
            'res_model': 'edu.module.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_student_line_id': self.id,
                'default_module_id': self.current_module_id.id,
                'default_amount': config.module_price,
            }
        }

    
    def check_and_freeze_if_unpaid(self):
        """Check if student should be frozen due to unpaid module"""
        self.ensure_one()

        config = self.env['edu.config'].get_config()

        module_name = self.current_module_id.name if self.current_module_id else _("Unknown Module")
        module_seq = self.current_module_id.sequence if self.current_module_id else 0

        # If completed full module but not paid
        if self.lessons_in_current_module >= config.lessons_per_module and not self.current_module_paid:
            self.write({'state': 'frozen'})
            self.group_id.message_post(
                body=_("⚠️ Student %s frozen: Module %s (%d) not fully paid") % (
                    self.student_id.name,
                    module_name,
                    module_seq
                )
            )
            return True

        # If payment overdue
        if self.lessons_in_current_module >= config.full_payment_lesson and not self.current_module_paid:
            self.write({'state': 'frozen'})
            self.group_id.message_post(
                body=_("⚠️ Student %s frozen: Payment overdue (Lesson %d, Module %s (%d) not paid)") % (
                    self.student_id.name,
                    self.lessons_in_current_module,
                    module_name,
                    module_seq
                )
            )
            return True

        return False

    
    
    def action_remove_from_group(self):
        """Guruhdan chiqarish: soft-remove a student from the group.

        The enrollment is marked 'cancelled' (label: Guruhdan chetlatilgan)
        rather than deleted, so the student's lesson/payment history stays
        intact and they can be re-added later via action_restore_to_group.
        Cancelled students are excluded from attendance rosters.
        """
        for line in self:
            if line.state == "cancelled":
                continue
            line.write({"state": "cancelled"})
            line.group_id.message_post(
                body=_("➖ %s guruhdan chetlatildi.") % (line.student_id.name or "")
            )

    def action_restore_to_group(self):
        """Guruhga qo'shish: restore a previously removed student.

        Sets the enrollment back to 'active'; the student keeps the module and
        lesson position they had when they were removed.
        """
        for line in self:
            if line.state != "cancelled":
                continue
            line.write({"state": "active"})
            line.group_id.message_post(
                body=_("➕ %s qayta guruhga qo'shildi.") % (line.student_id.name or "")
            )

    def increment_lesson_count(self):
        """Increment lesson count and handle module completion"""
        self.ensure_one()

        config = self.env['edu.config'].get_config()

        if not self.current_module_id:
            first_module = self.env["edu.module"].search([], order="sequence asc", limit=1)
            if not first_module:
                raise UserError(_("No modules found. Please create modules first."))
            self.current_module_id = first_module.id

        new_lesson_count = self.lessons_in_current_module + 1

        # Module completed
        if new_lesson_count > config.lessons_per_module:

            next_module = self.env["edu.module"].search([
                ("sequence", "=", self.current_module_id.sequence + 1)
            ], limit=1)

            if not next_module:
                raise UserError(_("Next module not found. Please create it."))

            self.write({
                "current_module_id": next_module.id,
                "lessons_in_current_module": 1,
                "current_module_paid": False,
                "current_module_payment_amount": 0.0,
            })

            self.group_id.message_post(
                body=_("✅ Student %s completed %s, moved to %s") % (
                    self.student_id.name,
                    self.current_module_id.name,
                    next_module.name
                )
            )
        else:
            self.write({
                "lessons_in_current_module": new_lesson_count
            })

    def decrement_lesson_count(self):
        """Reverse one increment_lesson_count step (attendance reset to draft).

        Mirrors the advance logic: steps back within the module, or back into
        the previous module (at its last lesson) when the increment had just
        advanced it. Payment flags cleared by the advance cannot be restored —
        acceptable, resets normally happen right after a wrong confirm."""
        self.ensure_one()

        config = self.env['edu.config'].get_config()
        count = self.lessons_in_current_module

        if count > 1:
            self.write({"lessons_in_current_module": count - 1})
        elif count == 1 and self.current_module_id and self.current_module_id != self.starting_module_id:
            prev_module = self.env["edu.module"].search([
                ("sequence", "=", self.current_module_id.sequence - 1)
            ], limit=1)
            if prev_module:
                self.write({
                    "current_module_id": prev_module.id,
                    "lessons_in_current_module": config.lessons_per_module,
                })
            else:
                self.write({"lessons_in_current_module": 0})
        else:
            self.write({"lessons_in_current_module": max(count - 1, 0)})

    _sql_constraints = [
        (
            "group_student_unique",
            "unique(group_id, student_id)",
            "Student already exists in this group.",
        )
    ]