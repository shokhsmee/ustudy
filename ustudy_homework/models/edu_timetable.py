# ustudy_homework/models/edu_timetable.py
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class EduTimetable(models.Model):
    _inherit = "edu.timetable"

    homework_id = fields.Many2one(
        "edu.homework",
        string="Homework",
        compute="_compute_homework_id",
        store=True,          # ✅ MUHIM
        index=True,
    )

    submitted_count = fields.Integer(compute="_compute_homework_stats", store=False)
    group_student_count = fields.Integer(compute="_compute_homework_stats", store=False)
    submission_ratio = fields.Char(compute="_compute_homework_stats", store=False)

    # The lesson's OWN Dars vazifasi (group task created by the Darsni
    # yakunlash wizard) — unlike homework_id it never falls back to the
    # course-wide slide homework, so the Topshiriqlar lesson list can show
    # empty vazifa columns until the teacher actually assigns one.
    lesson_task_id = fields.Many2one(
        "edu.homework",
        string="Dars vazifasi",
        compute="_compute_lesson_task_id",
        store=False,
    )
    task_number = fields.Char(
        related="lesson_task_id.task_number", string="Vazifa raqami", readonly=True)
    task_assigned_datetime = fields.Datetime(
        related="lesson_task_id.assigned_datetime", string="Vazifa berilgan vaqt",
        readonly=True)
    task_due_date = fields.Date(
        related="lesson_task_id.due_date", string="Deadline", readonly=True)
    task_done_ratio = fields.Char(
        related="lesson_task_id.done_ratio", string="Vazifa bajarish holati",
        readonly=True)
    # Char (not the related integer) so lessons without a task render an
    # EMPTY cell instead of a misleading 0.
    task_ungraded_display = fields.Char(
        string="Tekshirilmagan",
        compute="_compute_task_ungraded_display",
        store=False,
    )
    # Uzbek lesson status for the Topshiriqlar list (mockup wording).
    dars_holati = fields.Char(
        string="Dars holati",
        compute="_compute_dars_holati",
        store=False,
    )

    def _compute_lesson_task_id(self):
        ids = [r.id for r in self if isinstance(r.id, int)]
        by_tt = {}
        if ids:
            tasks = self.env["edu.homework"].search(
                [("timetable_id", "in", ids)], order="id asc")
            for task in tasks:
                by_tt.setdefault(task.timetable_id.id, task)
        for rec in self:
            rec.lesson_task_id = by_tt.get(rec.id) if isinstance(rec.id, int) else False

    def _compute_task_ungraded_display(self):
        for rec in self:
            task = rec.lesson_task_id
            rec.task_ungraded_display = str(task.ungraded_count) if task else ""

    def _compute_dars_holati(self):
        labels = {
            "scheduled": "Boshlanmagan",
            "in_progress": "Boshlangan",
            "completed": "Yakunlangan",
            "cancelled": "Bekor qilingan",
        }
        for rec in self:
            rec.dars_holati = labels.get(rec.state or "", "")

    def action_open_lesson_task(self):
        """Open this lesson's Dars vazifasi form (per-student roster)."""
        self.ensure_one()
        if not self.lesson_task_id:
            raise UserError(_("Bu dars uchun hali dars vazifasi qo'shilmagan."))
        return {
            "name": self.lesson_task_id.name,
            "type": "ir.actions.act_window",
            "res_model": "edu.homework",
            "res_id": self.lesson_task_id.id,
            "view_mode": "form",
            "views": [(self.env.ref("ustudy_homework.view_edu_homework_group_task_form").id, "form")],
        }

    homework_pass_mark = fields.Float(
        string="Pass Ball",
        related="homework_id.pass_mark",
        readonly=True,
    )

    # Editable subset of this lesson's homework submissions, limited to the
    # students enrolled in this timetable's group. Lets a teacher add a "ball"
    # (mark) right from the timetable form's Vazifalar tab — exactly like the
    # homework form's Submissions page. Not stored; persistence is handled in
    # write()/create() by forwarding the inline edits to the real submissions
    # (same idiom as hr.employee.certification_ids in core hr_skills).
    homework_submission_ids = fields.One2many(
        "edu.homework.submission",
        compute="_compute_homework_submission_ids",
        readonly=False,
        string="Submissions",
    )

    # Live roster of every student in this lesson's group together with their
    # homework result for THIS lesson's slide. Backed by the
    # edu.student.lesson.report SQL view (one row per student per lesson), so
    # all students always show — without creating placeholder submission rows
    # that would pollute submission counts/ratios. Ball/Izoh are editable
    # inline: the report model's write() redirects them to the row's real
    # edu.homework.submission (creating one for never-submitted students).
    lesson_report_ids = fields.One2many(
        "edu.student.lesson.report",
        "timetable_id",
        string="Talabalar holati",
    )

    @api.depends("slide_id")
    def _compute_homework_id(self):
        # The lesson's own "Dars vazifasi" (homework created for THIS timetable
        # by the Darsni yakunlash wizard) wins; otherwise fall back to the
        # course-wide slide homework. Group-scoped tasks of OTHER lessons or
        # groups must never be picked up, hence group_id = False on the
        # fallback. With no slide selected there is no fallback (we must NOT
        # grab any homework in the course channel, or unrelated homework would
        # show up on slide-less lessons).
        Homework = self.env["edu.homework"]
        for rec in self:
            hw = False
            if isinstance(rec.id, int):
                hw = Homework.search([
                    ("timetable_id", "=", rec.id),
                    ("is_published", "=", True),
                ], limit=1)
            if not hw and rec.slide_id:
                hw = Homework.search([
                    ("slide_id", "=", rec.slide_id.id),
                    ("is_published", "=", True),
                    ("group_id", "=", False),
                ], limit=1)
            rec.homework_id = hw.id if hw else False

    def _group_student_partner_ids(self):
        self.ensure_one()
        return self.group_id.student_line_ids.mapped("student_id").ids

    @api.depends("group_id", "homework_id")
    def _compute_homework_stats(self):
        Submission = self.env["edu.homework.submission"]
        for rec in self:
            total = rec.group_id.student_count or 0
            rec.group_student_count = total

            if not rec.homework_id or total == 0:
                rec.submitted_count = 0
                rec.submission_ratio = f"0/{total}" if total else "0/0"
                continue

            student_ids = set(rec._group_student_partner_ids())
            # Count distinct students who submitted (a resubmission is still one
            # student), so the ratio matches the one-row-per-student roster.
            submitted_students = rec.homework_id.submission_ids.filtered(
                lambda s: s.student_id.id in student_ids
            ).mapped("student_id")
            submitted = len(submitted_students)
            rec.submitted_count = submitted
            rec.submission_ratio = f"{submitted}/{total}"

    @api.depends("homework_id", "homework_id.submission_ids", "group_id.student_line_ids.student_id")
    def _compute_homework_submission_ids(self):
        """Build a one-row-per-student roster for the Vazifalar tab.

        Every student enrolled in the group gets exactly one row:
          * students with submissions -> their latest submission (real record),
            so the teacher edits the existing ball/comment in place;
          * students who never submitted -> an in-memory placeholder row in the
            ``not_submitted`` state. Entering a ball on such a row creates a real
            submission on the student's behalf (see write-back below).

        Resubmissions are collapsed: only the newest submission is shown, and its
        ``attempt_count`` (>1) flags that the student submitted more than once.
        """
        Submission = self.env["edu.homework.submission"]
        for rec in self:
            if not rec.homework_id:
                rec.homework_submission_ids = Submission
                continue

            students = rec.group_id.student_line_ids.mapped("student_id")
            student_ids = set(students.ids)
            subs = rec.homework_id.submission_ids.filtered(
                lambda s: s.student_id.id in student_ids
            )
            # Keep the newest submission per student (newest first).
            latest_by_student = {}
            for sub in subs.sorted(key=lambda s: (s.submit_date or s.create_date, s.id), reverse=True):
                latest_by_student.setdefault(sub.student_id.id, sub)

            rows = Submission
            for student in students:
                sub = latest_by_student.get(student.id)
                if not sub:
                    sub = Submission.new({
                        "homework_id": rec.homework_id.id,
                        "student_id": student.id,
                        "state": "not_submitted",
                    })
                rows |= sub
            rec.homework_submission_ids = rows

    def _apply_homework_submission_commands(self, commands):
        """Persist inline edits made in the Vazifalar tab.

        ``homework_submission_ids`` is a non-stored computed field, so the ORM
        won't write it for us. UPDATE commands (the teacher grades an existing
        submission) are forwarded to the real record. CREATE commands come from
        grading a ``not_submitted`` placeholder row: the teacher is grading a
        student who never submitted, so we create a real submission on their
        behalf. Delete is ignored."""
        if not commands:
            return
        Submission = self.env["edu.homework.submission"]
        allowed = {
            "homework_id", "student_id", "mark", "teacher_comment",
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
                if not vals.get("homework_id") or not vals.get("student_id"):
                    continue
                # Skip empty placeholder rows the teacher never touched.
                if vals.get("mark") in (None, False) and not vals.get("teacher_comment"):
                    continue
                if not vals.get("user_id"):
                    student = self.env["res.partner"].browse(vals["student_id"])
                    user = student.user_ids[:1]
                    vals["user_id"] = user.id if user else self.env.user.id
                Submission.create(vals)

    @api.model_create_multi
    def create(self, vals_list):
        # A brand-new timetable has no submissions to grade yet; drop the key so
        # the non-stored computed field doesn't reach super().create().
        for vals in vals_list:
            vals.pop("homework_submission_ids", None)
        return super().create(vals_list)

    def write(self, vals):
        sub_commands = vals.pop("homework_submission_ids", None)
        res = super().write(vals)
        self._apply_homework_submission_commands(sub_commands)
        return res

    def action_mark_completed(self):
        """Completing a lesson goes through the Darsni yakunlash wizard: the
        teacher defines the group's Dars vazifasi (extra group-scoped
        homework) and the lesson is completed by the wizard's buttons. The
        wizard calls back with skip_lesson_task_wizard to actually complete.
        A lesson that already has its own task completes directly."""
        if self.env.context.get("skip_lesson_task_wizard") or len(self) != 1:
            return super().action_mark_completed()
        if self.env["edu.homework"].search_count([("timetable_id", "=", self.id)]):
            return super().action_mark_completed()
        return {
            "name": _("Darsni yakunlash"),
            "type": "ir.actions.act_window",
            "res_model": "edu.lesson.complete.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_timetable_id": self.id},
        }

    def action_view_group_homework_submissions(self):
        self.ensure_one()
        if not self.homework_id:
            raise UserError(_("No homework linked to this timetable lesson."))

        student_ids = self._group_student_partner_ids()
        return {
            "name": _("Submissions"),
            "type": "ir.actions.act_window",
            "res_model": "edu.homework.submission",
            "view_mode": "list,form",
            "domain": [
                ("homework_id", "=", self.homework_id.id),
                ("student_id", "in", student_ids),
            ],
        }
