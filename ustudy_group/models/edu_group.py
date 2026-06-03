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

    lesson_days = fields.Many2many(
        'edu.weekday',
        string='Lesson Days',
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

    @api.depends("timetable_ids.state")
    def _compute_started_lessons_count(self):
        for rec in self:
            started = rec.timetable_ids.filtered(lambda t: t.state in ["in_progress", "completed"])
            rec.started_lessons_count = len(started)

    @api.depends("timetable_ids.state", "start_lesson_number")
    def _compute_module_boundary(self):
        config = self.env["edu.config"].get_config()
        lpm = config.lessons_per_module or 12
        for rec in self:
            started = len(rec.timetable_ids.filtered(lambda t: t.state in ["in_progress", "completed"]))
            course_offset = (rec.start_lesson_number or 1) - 1 + started
            position = course_offset % lpm
            rec.is_at_module_start = (position == 0)
            rec.lessons_until_next_module = 0 if position == 0 else (lpm - position)


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

        Only allowed when the group is positioned at a module boundary — i.e.
        the next lesson starts a fresh module. This keeps finance clean
        (a mid-joiner always begins paying from a whole module, never half a one).
        """
        self.ensure_one()
        if not self.is_at_module_start:
            raise UserError(_(
                "Bu guruhga hozir yangi o'quvchi qo'shib bo'lmaydi. "
                "Guruh modul boshlanishida bo'lishi kerak. "
                "Keyingi modulgacha %s ta dars qoldi."
            ) % self.lessons_until_next_module)
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

    debt_status = fields.Selection(
        [
            ('paid', "To'langan"),
            ('debtor', "Qarzdor"),
        ],
        string="To'lov holati",
        compute="_compute_debt_status",
        store=False,
    )

    @api.depends("debt_lessons_count", "paid_lessons_count")
    def _compute_debt_status(self):
        for rec in self:
            rec.debt_status = 'debtor' if rec.debt_lessons_count > rec.paid_lessons_count else 'paid'
    
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
        payment_type = self.env['cc.payment.type'].search([
            ('code', '=', 'student_module'),
            ('type_category', '=', 'student')
        ], limit=1)
        has_link = "student_line_id" in self.env["cc.finance"]._fields

        for rec in self:
            if not payment_type or not has_link or not rec.id:
                rec.paid_amount_total = 0.0
                continue

            domain = [
                ("student_line_id", "=", rec.id),
                ("payment_type_id", "=", payment_type.id),
                ("transaction_type", "=", "income"),
                ("state", "=", "confirmed"),
            ]
            # Hide past-module payments for mid-joiners (shouldn't normally exist,
            # but excluded for safety so the per-lesson conversion stays consistent).
            domain += rec._get_module_scope_domain()

            payments = self.env["cc.finance"].search(domain)
            rec.paid_amount_total = sum(payments.mapped("amount"))

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

    def _compute_passed_lessons(self):
        Timetable = self.env["edu.timetable"]
        config = self.env["edu.config"].get_config()
        lpm = config.lessons_per_module or 12
        per_lesson = (config.module_price / lpm) if lpm else 0.0

        for rec in self:
            if not rec.group_id:
                rec.passed_lessons_count = 0
                rec.passed_lessons_amount = 0.0
                continue

            domain = [
                ("group_id", "=", rec.group_id.id),
                ("state", "in", ["in_progress", "completed"]),
            ]
            if rec.enrollment_date:
                domain.append(("start_date", ">=", rec.enrollment_date))

            count = Timetable.search_count(domain)
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
        # this still computes (as 0) when that module isn't installed.
        has_link = "student_line_id" in self.env["cc.finance"]._fields
        for rec in self:
            if not has_link or not rec.id:
                rec.student_balance = 0.0
                continue
            payments = self.env["cc.finance"].search([
                ("student_line_id", "=", rec.id),
                ("state", "=", "confirmed"),
            ])
            balance = 0.0
            for p in payments:
                if p.transaction_type == "income":
                    balance += p.amount
                elif p.transaction_type == "expense":
                    balance -= p.amount
            rec.student_balance = balance

    
    finance_count = fields.Integer(
        compute="_compute_finance_count",
        string="Payments"
    )

    def _compute_finance_count(self):
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