from odoo import api, fields, models, _

class EduHomework(models.Model):
    _name = "edu.homework"
    _description = "Lesson Homework"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(string="Title", required=True, tracking=True)
    slide_id = fields.Many2one('slide.slide', string='Lesson/Slide', ondelete='set null')

    channel_id = fields.Many2one(
        "slide.channel",
        string="Course / Channel",
        required=False,
        tracking=True,
        ondelete='set null',
        index=True,
    )

    description = fields.Text(string="Description")
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")
    due_date = fields.Date(string="Due Date")

    teacher_id = fields.Many2one(
        "hr.employee",
        string="Teacher",
        ondelete="set null",
    )

    is_published = fields.Boolean(string="Published", default=True)

    # ---------- group lesson task (Dars vazifasi) ----------
    # A homework with group_id set is a "Dars vazifasi": an extra assignment a
    # teacher gives ONE group when completing a lesson (Darsni yakunlash
    # wizard). It is only visible to that group's students; homework with no
    # group stays course-wide (the auto-created slide homework).
    group_id = fields.Many2one(
        "edu.group",
        string="Guruh",
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    timetable_id = fields.Many2one(
        "edu.timetable",
        string="Dars (jadval)",
        ondelete="set null",
        index=True,
        help="The lesson at whose completion this task was assigned.",
    )
    assigned_datetime = fields.Datetime(
        string="Vazifa berilgan vaqt",
        default=fields.Datetime.now,
    )
    task_number = fields.Char(
        string="Vazifa raqami",
        readonly=True,
        copy=False,
        help="Sequential number of the task within its group (001, 002, ...).",
    )
    lesson_label = fields.Char(
        string="Dars",
        compute="_compute_lesson_label",
        store=False,
    )
    done_ratio = fields.Char(
        string="Vazifa bajarish holati",
        compute="_compute_group_progress",
        store=False,
        help="Students who submitted / students in the group.",
    )
    ungraded_count = fields.Integer(
        string="Tekshirilmagan",
        compute="_compute_group_progress",
        store=False,
        help="Students whose latest submission is still waiting for a grade.",
    )

    # One-row-per-student roster for the group task form: every student of the
    # group appears once — real latest submission when they submitted, an
    # in-memory not_submitted placeholder otherwise. Same idiom as
    # edu.timetable.homework_submission_ids; persistence handled in
    # create()/write() by forwarding the commands to real submissions.
    group_submission_ids = fields.One2many(
        "edu.homework.submission",
        compute="_compute_group_submission_ids",
        readonly=False,
        string="O'quvchilar holati",
    )

    @api.depends("timetable_id", "timetable_id.lesson_sequence", "slide_id", "slide_id.lesson_no")
    def _compute_lesson_label(self):
        for rec in self:
            no = rec.timetable_id.lesson_sequence or rec.slide_id.lesson_no or 0
            rec.lesson_label = f"{no}-dars" if no else ""

    @api.depends("group_id.student_line_ids.student_id",
                 "submission_ids.state", "submission_ids.student_id")
    def _compute_group_progress(self):
        for rec in self:
            if rec.group_id:
                students = rec.group_id.student_line_ids.student_id
                subs = rec.submission_ids.filtered(lambda s: s.student_id in students)
                total = len(students)
            else:
                subs = rec.submission_ids
                total = len(subs.mapped("student_id"))
            # newest submission per student (higher id = newer)
            latest_by_student = {}
            for sub in subs.sorted(key=lambda s: s.id or 0, reverse=True):
                latest_by_student.setdefault(sub.student_id.id, sub)
            rec.done_ratio = f"{len(latest_by_student)}/{total}"
            rec.ungraded_count = sum(
                1 for s in latest_by_student.values() if s.state == "submitted"
            )

    @api.depends("group_id.student_line_ids.student_id", "submission_ids")
    def _compute_group_submission_ids(self):
        Submission = self.env["edu.homework.submission"]
        for rec in self:
            if not rec.group_id or not isinstance(rec.id, int):
                rec.group_submission_ids = rec.submission_ids
                continue
            students = rec.group_id.student_line_ids.mapped("student_id")
            student_ids = set(students.ids)
            subs = rec.submission_ids.filtered(lambda s: s.student_id.id in student_ids)
            latest_by_student = {}
            for sub in subs.sorted(key=lambda s: s.id or 0, reverse=True):
                latest_by_student.setdefault(sub.student_id.id, sub)
            rows = Submission
            for student in students:
                sub = latest_by_student.get(student.id)
                if not sub:
                    sub = Submission.new({
                        "homework_id": rec.id,
                        "student_id": student.id,
                        "state": "not_submitted",
                    })
                rows |= sub
            rec.group_submission_ids = rows

    def _apply_group_submission_commands(self, commands):
        """Persist inline grading done in the group-task roster.

        The roster is a non-stored computed one2many, so the ORM won't write
        it. UPDATE commands go to the real submission; CREATE commands come
        from grading a not_submitted placeholder — a real submission is
        created on the student's behalf. Deletes are ignored."""
        if not commands:
            return
        self.ensure_one()
        Submission = self.env["edu.homework.submission"]
        allowed = {
            "student_id", "mark", "teacher_comment",
            "comment", "submit_date", "user_id",
        }
        for command in commands:
            if not command:
                continue
            op = command[0]
            if op == 1:  # Command.UPDATE
                Submission.browse(command[1]).write(command[2])
            elif op == 0:  # Command.CREATE (graded a not_submitted student)
                vals = {k: v for k, v in (command[2] or {}).items() if k in allowed}
                if not vals.get("student_id"):
                    continue
                # Skip placeholder rows the teacher never touched.
                if vals.get("mark") in (None, False) and not vals.get("teacher_comment"):
                    continue
                if not vals.get("user_id"):
                    student = self.env["res.partner"].browse(vals["student_id"])
                    user = student.user_ids[:1]
                    vals["user_id"] = user.id if user else self.env.user.id
                vals["homework_id"] = self.id
                Submission.create(vals)

    def _next_task_number(self):
        """Next per-group sequential number, zero-padded (001, 002, ...)."""
        self.ensure_one()
        if not self.group_id:
            return False
        numbers = self.search([
            ("group_id", "=", self.group_id.id),
            ("id", "!=", self.id),
        ]).mapped("task_number")
        max_no = 0
        for value in numbers:
            try:
                max_no = max(max_no, int(value))
            except (TypeError, ValueError):
                continue
        return "%03d" % (max_no + 1)

    def is_visible_for(self, user=None):
        """Whether this homework may be shown to ``user`` on the website.

        Published is necessary but not sufficient: if the homework is tied to a
        lesson slide, the user's group must have STARTED that lesson (timetable
        in_progress/completed). Homework not tied to any slide cannot be gated by
        a timetable, so it stays visible once published.

        Group lesson tasks (group_id set) are additionally restricted to the
        students of that group — other groups on the same course/slide must
        never see them. Officers/teachers always pass, for management/preview.
        """
        self.ensure_one()
        user = user or self.env.user
        if not self.is_published:
            return False
        if self.group_id and not user.has_group("website_slides.group_website_slides_officer"):
            partner = user.partner_id
            if not partner or partner.id not in self.group_id.student_line_ids.student_id.ids:
                return False
        if not self.slide_id:
            return True
        return self.slide_id.lesson_started_for(user)

    mark_count = fields.Integer(string="Marks", compute="_compute_mark_count", store=False)
    mark_ids = fields.One2many("edu.homework.mark", "homework_id", string="Marks")

    submission_ids = fields.One2many("edu.homework.submission", "homework_id", string="Submissions")
    submission_count = fields.Integer(string="Submissions", compute="_compute_submission_count")
    
    pass_mark = fields.Float(string="Pass Ball", default=60.0)

    # Student portal fields
    current_user_submission_id = fields.Many2one(
        "edu.homework.submission",
        string="My Submission",
        compute="_compute_current_user_submission",
        store=False,
    )
    current_user_status = fields.Selection(
        [
            ("not_submitted", "In Progress"),
            ("submitted", "Submitted"),
            ("graded", "Passed"),
            ("failed", "Failed"),
        ],
        string="Status",
        compute="_compute_current_user_submission",
        store=False,
    )
    current_user_mark = fields.Float(
        string="My Mark",
        compute="_compute_current_user_submission",
        store=False,
    )

    @api.depends_context("uid")
    def _compute_current_user_submission(self):
        """Compute current user's submission status and mark"""
        for rec in self:
            user = self.env.user
            partner = user.partner_id
            
            submission = self.env["edu.homework.submission"].search([
                ("homework_id", "=", rec.id),
                ("student_id", "=", partner.id),
            ], limit=1)
            
            if submission:
                rec.current_user_submission_id = submission.id
                rec.current_user_status = submission.state
                rec.current_user_mark = submission.mark
            else:
                rec.current_user_submission_id = False
                rec.current_user_status = "not_submitted"
                rec.current_user_mark = 0.0

    @api.depends("submission_ids")
    def _compute_submission_count(self):
        for rec in self:
            rec.submission_count = len(rec.submission_ids)

    @api.depends("mark_ids")
    def _compute_mark_count(self):
        for rec in self:
            rec.mark_count = len(rec.mark_ids)

    @api.model
    def create(self, vals_list):
        if not isinstance(vals_list, list):
            vals_list = [vals_list]

        default_slide_id = self.env.context.get('default_slide_id')

        roster_commands = []
        for vals in vals_list:
            # non-stored computed roster must never reach super().create()
            roster_commands.append(vals.pop('group_submission_ids', None))
            slide_id = vals.get('slide_id') or default_slide_id
            if slide_id and not vals.get('channel_id'):
                slide = self.env['slide.slide'].browse(slide_id)
                if slide and slide.channel_id:
                    vals['channel_id'] = slide.channel_id.id

        records = super(EduHomework, self).create(vals_list)

        for rec, commands in zip(records, roster_commands):
            if rec.group_id and not rec.task_number:
                rec.task_number = rec._next_task_number()
            if commands:
                rec._apply_group_submission_commands(commands)

        for rec in records:
            if rec.channel_id:
                if not rec.pass_mark or rec.pass_mark == 60.0:
                    rec.pass_mark = rec.channel_id.homework_pass_mark or 60.0

            if not rec.teacher_id and rec.channel_id:
                group = self.env["edu.group"].search([
                    ("course_id", "=", rec.channel_id.id),
                    ("teacher_id", "!=", False)
                ], limit=1)
                if group and group.teacher_id:
                    employee = self.env["hr.employee"].search(
                        [("user_id", "=", group.teacher_id.id)],
                        limit=1,
                    )
                    if employee:
                        rec.teacher_id = employee.id

        records._sync_timetable_homework_flags()
        return records

    def write(self, vals):
        roster_commands = vals.pop('group_submission_ids', None)
        if roster_commands:
            for rec in self:
                rec._apply_group_submission_commands(roster_commands)
            if not vals:
                return True

        if 'slide_id' in vals and vals.get('slide_id') and not vals.get('channel_id'):
            slide = self.env['slide.slide'].browse(vals.get('slide_id'))
            if slide and slide.channel_id:
                vals['channel_id'] = slide.channel_id.id

        slides_before = self.mapped('slide_id') if {'slide_id', 'is_published'} & set(vals) else self.env['slide.slide']

        res = super().write(vals)

        for rec in self.filtered(lambda r: not r.teacher_id and r.channel_id):
            group = self.env["edu.group"].search([
                ("course_id", "=", rec.channel_id.id),
                ("teacher_id", "!=", False)
            ], limit=1)
            if group and group.teacher_id:
                employee = self.env["hr.employee"].search(
                    [("user_id", "=", group.teacher_id.id)],
                    limit=1,
                )
                if employee:
                    rec.teacher_id = employee.id

        if {'slide_id', 'is_published', 'timetable_id', 'group_id'} & set(vals):
            slides_after = self.mapped('slide_id')
            self._sync_timetable_homework_flags(extra_slides=slides_before | slides_after)
        return res

    def unlink(self):
        slides = self.mapped('slide_id')
        timetables = self.mapped('timetable_id')
        res = super().unlink()
        self.browse()._sync_timetable_homework_flags(
            extra_slides=slides, extra_timetables=timetables)
        return res

    def _sync_timetable_homework_flags(self, extra_slides=None, extra_timetables=None):
        """Recompute has_homework / homework_id on timetables whose slide matches
        (or that are directly linked via timetable_id — group lesson tasks).

        Stored compute fields on edu.timetable depend only on slide_id, so they
        don't auto-invalidate when an edu.homework is added/published/removed.
        This is the explicit invalidation hook."""
        if 'edu.timetable' not in self.env:
            return
        Timetable = self.env['edu.timetable']
        slides = self.mapped('slide_id') | (extra_slides or self.env['slide.slide'])
        linked = self.mapped('timetable_id') | (extra_timetables or Timetable)
        timetables = Timetable
        if slides:
            timetables |= Timetable.search([('slide_id', 'in', slides.ids)])
        timetables |= linked.exists()
        if not timetables:
            return
        timetables._compute_has_homework()
        if 'homework_id' in Timetable._fields:
            timetables._compute_homework_id()

    def action_open_submissions(self):
        """Open this homework's real submissions (with the students' files) —
        the grading surface behind the group-task roster."""
        self.ensure_one()
        return {
            "name": _("Topshiriqlar - %s") % self.name,
            "type": "ir.actions.act_window",
            "res_model": "edu.homework.submission",
            "view_mode": "list,form",
            "domain": [("homework_id", "=", self.id)],
            "context": dict(self.env.context or {}, default_homework_id=self.id),
        }

    def action_open_marks(self):
        self.ensure_one()
        return {
            "name": _("Marks"),
            "type": "ir.actions.act_window",
            "res_model": "edu.homework.mark",
            "domain": [("homework_id", "=", self.id)],
            "view_mode": "list,form",
            "context": dict(self.env.context or {}, default_homework_id=self.id),
        }

    def unlink_slide(self):
        for rec in self:
            rec.slide_id = False