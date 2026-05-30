from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta


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

    student_count = fields.Integer(
        string="Students",
        compute="_compute_student_count",
        store=False,
    )

    # -----------------------------------------------------------------
    # Capacity / Soft Overbooking
    # -----------------------------------------------------------------
    max_students = fields.Integer(
        string="Max Students",
        default=16,
        tracking=True,
        help="Soft seat limit for this group (0 = unlimited). It can be "
             "exceeded by a user holding the 'Capacity Override' right, or "
             "when 'Allow Overbooking' is enabled on the group.",
    )
    allow_overbooking = fields.Boolean(
        string="Allow Overbooking",
        tracking=True,
        help="If enabled, this group may exceed its capacity even without the "
             "'Capacity Override' right.",
    )
    active_student_count = fields.Integer(
        string="Active Students",
        compute="_compute_capacity_info",
        store=False,
        help="Number of enrollments currently occupying a seat (active/frozen).",
    )
    seat_limit = fields.Integer(
        string="Effective Seat Limit",
        compute="_compute_capacity_info",
        store=False,
        help="Smallest of the group capacity and the assigned room capacities "
             "(0 = unlimited).",
    )
    available_seats = fields.Integer(
        string="Available Seats",
        compute="_compute_capacity_info",
        store=False,
    )
    is_over_capacity = fields.Boolean(
        string="Over Capacity",
        compute="_compute_capacity_info",
        store=False,
    )

    # -----------------------------------------------------------------
    # Floating schedule (replaces hardcoded single lesson time)
    # -----------------------------------------------------------------
    schedule_ids = fields.One2many(
        "edu.group.schedule",
        "group_id",
        string="Weekly Schedule",
        help="Floating weekly slots. Each line is one weekday + time range, "
             "e.g. Monday 14:00-15:30 and Wednesday 18:00-19:30.",
    )
    schedule_count = fields.Integer(
        string="Schedule Slots",
        compute="_compute_schedule_count",
        store=False,
    )

    lesson_days = fields.Many2many(
        'edu.weekday',
        string='Lesson Days',
        help="Legacy single-time days. Kept for backward compatibility; the "
             "floating 'Weekly Schedule' lines take precedence when present.",
    )

    lesson_room = fields.Many2one(
        "edu.room",
        string="Lesson Room",
        ondelete="set null",
        tracking=True,
    )

    notes = fields.Text(string="Notes")
    active = fields.Boolean(default=True)


    started_lessons_count = fields.Integer(
        string="Started Lessons",
        compute="_compute_started_lessons_count",
        store=False
    )

    @api.depends("timetable_ids.state")
    def _compute_started_lessons_count(self):
        for rec in self:
            started = rec.timetable_ids.filtered(lambda t: t.state in ["in_progress", "completed"])
            rec.started_lessons_count = len(started)


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
    def _compute_student_count(self):
        for group in self:
            group.student_count = len(group.student_line_ids)

    # -----------------------------------------------------------------
    # Capacity / Soft Overbooking logic
    # -----------------------------------------------------------------
    # Enrollment states that actually occupy a seat.
    OCCUPYING_STATES = ("active", "frozen")

    def _occupied_seats(self):
        """How many enrollments currently take up a seat in this group."""
        self.ensure_one()
        return len(
            self.student_line_ids.filtered(lambda l: l.state in self.OCCUPYING_STATES)
        )

    def _seat_limit(self):
        """Return ``(limit, source_label)`` for the binding capacity.

        The effective limit is the *smallest* of the group capacity and the
        capacity of any room the group uses. ``0`` means "unlimited".
        """
        self.ensure_one()
        candidates = []
        if self.max_students:
            candidates.append((self.max_students, _("group capacity")))
        rooms = self.lesson_room | self.schedule_ids.mapped("room_id")
        for room in rooms:
            if room.capacity:
                candidates.append((room.capacity, _("room '%s'") % room.name))
        if not candidates:
            return 0, ""
        return min(candidates, key=lambda c: c[0])

    @api.depends(
        "student_line_ids.state",
        "max_students",
        "lesson_room.capacity",
        "schedule_ids.room_id.capacity",
    )
    def _compute_capacity_info(self):
        for group in self:
            occupied = group._occupied_seats()
            limit, _source = group._seat_limit()
            group.active_student_count = occupied
            group.seat_limit = limit
            if limit:
                group.available_seats = limit - occupied
                group.is_over_capacity = occupied > limit
            else:
                group.available_seats = 0
                group.is_over_capacity = False

    @api.depends("schedule_ids")
    def _compute_schedule_count(self):
        for group in self:
            group.schedule_count = len(group.schedule_ids)

    def _capacity_override_allowed(self):
        """The escape hatch that makes the capacity rule *soft*.

        Overbooking is permitted when any of the following is true:
          * we run as superuser (data loading / migrations);
          * the group explicitly allows overbooking;
          * the current user holds the managerial 'Capacity Override' right.
        """
        self.ensure_one()
        if self.env.su:
            return True
        if self.allow_overbooking:
            return True
        return self.env.user.has_group("ustudy_group.group_capacity_manager")

    def _enforce_capacity(self):
        """Soft capacity enforcement, called whenever enrollments change.

        * Within the limit  -> nothing happens.
        * Over the limit and authorized -> the enrollment is accepted and an
          audit note is posted to the group chatter (no error).
        * Over the limit and NOT authorized -> a guiding, *overridable* error
          is raised. It is not a permanent hard wall: a manager (or the
          'Allow Overbooking' flag) can always let it through.
        """
        for group in self:
            limit, source = group._seat_limit()
            if not limit:
                continue
            occupied = group._occupied_seats()
            if occupied <= limit:
                continue
            if group._capacity_override_allowed():
                group._post_overbooking_note(occupied, limit, source)
            else:
                raise ValidationError(_(
                    "Group '%(group)s' is full: %(count)s / %(limit)s seats "
                    "used (%(source)s).\n\n"
                    "This is a soft limit. A user with the 'Capacity Override' "
                    "right can add extra students, or you can enable "
                    "'Allow Overbooking' (or raise 'Max Students') on the group.",
                    group=group.name,
                    count=occupied,
                    limit=limit,
                    source=source,
                ))

    def _post_overbooking_note(self, occupied, limit, source):
        self.ensure_one()
        self.message_post(body=_(
            "Overbooking allowed: %(count)s / %(limit)s seats used "
            "(%(source)s). Authorized by %(user)s.",
            count=occupied,
            limit=limit,
            source=source,
            user=self.env.user.display_name,
        ))

    @api.depends("slide_channel_id", "slide_channel_id.slide_ids")
    def _compute_group_lesson_count(self):
        for group in self:
            if group.slide_channel_id:
                group.course_count = len(group.slide_channel_id.slide_ids)
            else:
                group.course_count = 0

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
        """Open lessons for this group's course"""
        self.ensure_one()
        if self.slide_channel_id:
            return {
                'name': _('Course Lessons - %s', self.slide_channel_id.name),
                'type': 'ir.actions.act_window',
                'res_model': 'slide.slide',
                'view_mode': 'list,form',
                'domain': [('channel_id', '=', self.slide_channel_id.id)],
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
        """Open wizard to add a student to this running group from a specific date"""
        self.ensure_one()
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

    def action_start(self):
        """Change state to running"""
        self.write({'state': 'running'})

    def action_complete(self):
        """Change state to done"""
        self.write({'state': 'done'})
    
    def action_running(self):
        """Restart course - change state back to running"""
        self.write({'state': 'running'})


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
        """
        Opens the student attendance timeline (week view by default).
        Rows = students, blocks = lessons colored by attendance status.
        """
        self.ensure_one()
        return {
            "name": _("Davomat - %s") % self.name,
            "type": "ir.actions.act_window",
            "res_model": "edu.group.student.lesson.report",
            "view_mode": "timeline,list",
            "views": [
                (self.env.ref(
                    "ustudy_group.view_edu_student_lesson_report_timeline"
                ).id, "timeline"),
                (False, "list"),
            ],
            "domain": [("group_id", "=", self.id)],
            "context": {
                "default_group_id": self.id,
                # DO NOT pass search_default_group_id — not a field on report model
            },
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
    
    state = fields.Selection(
        [
            ("active", "Active"),
            ("completed", "Completed"),
            ("frozen", "Frozen"),
            ("cancelled", "Cancelled"),
        ],
        default="active",
    )

    enrollment_date = fields.Date(
        string="Enrollment Date",
        default=fields.Date.today,
        help="Date when student joined this group. Used to calculate attendance and module from that day.",
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
    
    
    def _compute_paid_amount_total(self):
        payment_type = self.env['cc.payment.type'].search([
            ('code', '=', 'student_module'),
            ('type_category', '=', 'student')
        ], limit=1)

        for rec in self:
            if not payment_type:
                rec.paid_amount_total = 0.0
                continue

            payments = self.env["cc.finance"].search([
                ("partner_id", "=", rec.student_id.id),
                ("payment_type_id", "=", payment_type.id),
                ("transaction_type", "=", "income"),
                ("state", "=", "confirmed"),
            ])

            rec.paid_amount_total = sum(payments.mapped("amount"))
    
    
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

        for rec in self:
            domain = [
                ("student_id", "=", rec.student_id.id),
                ("attendance_id.group_id", "=", rec.group_id.id),
                ("attendance_id.state", "=", "confirmed"),
                ("status", "=", "present"),
            ]
            if rec.enrollment_date:
                domain.append(("attendance_id.attendance_date", ">=", rec.enrollment_date))
            rec.attended_lessons_count = AttendanceLine.search_count(domain)

    
    finance_count = fields.Integer(
        compute="_compute_finance_count",
        string="Payments"
    )

    def _compute_finance_count(self):
        payment_type = self.env['cc.payment.type'].search([
            ('code', '=', 'student_module'),
            ('type_category', '=', 'student')
        ], limit=1)

        for rec in self:
            domain = [("partner_id", "=", rec.student_id.id)]
            if payment_type:
                domain.append(("payment_type_id", "=", payment_type.id))

            rec.finance_count = self.env["cc.finance"].search_count(domain)


    def action_view_student_finance(self):
        self.ensure_one()

        payment_type = self.env['cc.payment.type'].search([
            ('code', '=', 'student_module'),
            ('type_category', '=', 'student')
        ], limit=1)

        domain = [("partner_id", "=", self.student_id.id)]
        if payment_type:
            domain.append(("payment_type_id", "=", payment_type.id))
            
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

            if not vals.get("current_module_id"):
                start_lesson = (group.start_lesson_number or 1) if group else 1
                config = self.env['edu.config'].get_config()
                lpm = config.lessons_per_module or 12

                # 0-based offset into the full course lesson list
                course_offset = start_lesson - 1
                module_seq = course_offset // lpm + 1          # 1-based module sequence
                position_in_module = course_offset % lpm       # lessons already "done" in that module

                module = self.env["edu.module"].search([("sequence", "=", module_seq)], limit=1)
                if not module:
                    module = self.env["edu.module"].search([], order="sequence asc", limit=1)

                if module:
                    vals["current_module_id"] = module.id
                    # only pre-set position when group explicitly starts mid-course
                    if start_lesson > 1 and "lessons_in_current_module" not in vals:
                        vals["lessons_in_current_module"] = position_in_module

        records = super().create(vals_list)
        # Soft capacity check: never a permanent block, overridable by managers.
        records.mapped("group_id")._enforce_capacity()
        return records

    def write(self, vals):
        res = super().write(vals)
        # Re-evaluate capacity when a student joins another group or is
        # (re)activated, since either can push a group over its soft limit.
        if vals.get("group_id") or "state" in vals:
            self.mapped("group_id")._enforce_capacity()
        return res

    
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

    _sql_constraints = [
        (
            "group_student_unique",
            "unique(group_id, student_id)",
            "Student already exists in this group.",
        )
    ]
    # NOTE on multi-group enrollment (e.g. "Sky Chess" logic):
    # This model is a pure junction (link) table between a student
    # (res.partner) and an edu.group. The uniqueness above is scoped to the
    # PAIR (group_id, student_id), so the SAME student can be enrolled in any
    # number of DIFFERENT groups simultaneously. There is intentionally no
    # constraint limiting a student to a single group.