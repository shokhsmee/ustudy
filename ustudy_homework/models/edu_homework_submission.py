from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

# States that still wait for a teacher's ball. A resubmission is a first-class
# state ('resubmitted'), so every "not graded yet" check must cover both.
UNGRADED_STATES = ("submitted", "resubmitted")


class EduHomeworkSubmission(models.Model):
    _name = "edu.homework.submission"
    _description = "Homework Submission"

    # ungraded first (submitted / resubmitted), then graded, then failed;
    # newest first
    _order = "state_seq asc, submit_date desc, id desc"

    homework_id = fields.Many2one(
        "edu.homework", string="Homework", required=True, ondelete="cascade"
    )
    student_id = fields.Many2one(
        "res.partner",
        string="Student",
        required=True,
        domain=[("is_student", "=", True)],
    )
    user_id = fields.Many2one("res.users", string="User", required=True)
    submit_date = fields.Datetime(string="Submitted On", default=fields.Datetime.now, required=True)
    comment = fields.Text(string="Student Comment")

    attachment_ids = fields.Many2many(
        "ir.attachment",
        "edu_homework_submission_ir_attachment_rel",
        "submission_id",
        "attachment_id",
        string="Files",
    )

    state = fields.Selection(
        [
            ("not_submitted", "Not submitted"),
            ("submitted", "Topshirilgan"),
            ("resubmitted", "Qayta topshirilgan"),
            ("graded", "Passed"),
            ("failed", "Failed"),
        ],
        default="submitted",
        string="Status",
        tracking=True,
    )

    # Ordinal of this submission among the student's attempts at this homework
    # (1 = first submission, 2+ = resubmission). Stored, so rosters and the SQL
    # report view can show it without a per-row COUNT.
    attempt_no = fields.Integer(
        string="Urinish №",
        default=1,
        copy=False,
        readonly=True,
        index=True,
    )

    # Number of submissions this student made for this homework. >1 means the
    # student resubmitted. Used by the timetable Vazifalar roster to flag
    # resubmissions (the roster collapses to one row per student).
    attempt_count = fields.Integer(
        string="Attempts",
        compute="_compute_attempt_count",
        store=False,
    )

    def _compute_attempt_count(self):
        """One read_group for the whole recordset — this field is rendered on
        every row of the grading rosters, so a per-record search_count made the
        lists crawl."""
        real = self.filtered(lambda r: isinstance(r.id, int))
        # In-memory placeholder rows (students with no submission yet) have no
        # real id; they represent zero attempts.
        (self - real).attempt_count = 0
        if not real:
            return
        counts = {
            (homework.id, student.id): count
            for homework, student, count in self.env["edu.homework.submission"]._read_group(
                [
                    ("homework_id", "in", real.homework_id.ids),
                    ("student_id", "in", real.student_id.ids),
                ],
                groupby=["homework_id", "student_id"],
                aggregates=["__count"],
            )
        }
        for rec in real:
            rec.attempt_count = counts.get(
                (rec.homework_id.id, rec.student_id.id), 0)

    # used for correct ordering (submitted -> graded -> failed)
    state_seq = fields.Integer(
        string="State Seq",
        compute="_compute_state_seq",
        store=True,
        index=True,
    )

    @api.depends("state")
    def _compute_state_seq(self):
        # NB: 'resubmitted' shares 'submitted''s rank (both are waiting for a
        # ball) so the values of already-stored rows stay valid — no migration
        # of state_seq is needed when the new state is introduced.
        mapping = {
            "not_submitted": -1,
            "submitted": 0,
            "resubmitted": 0,
            "graded": 1,
            "failed": 2,
        }
        for rec in self:
            rec.state_seq = mapping.get(rec.state or "submitted", 99)

    mark = fields.Float(string="Mark")
    teacher_comment = fields.Text(string="Teacher Comment")

    pass_mark = fields.Float(related="homework_id.pass_mark", store=True, readonly=True)

    # Display-only columns for the group lesson-task roster (mockup: O'quvchi,
    # Dars, Guruh, Vazifa berilgan vaqt, Bahosi, Vazifa holat, Deadline).
    task_group_id = fields.Many2one(
        related="homework_id.group_id", string="Guruh", readonly=True)
    task_lesson_label = fields.Char(
        related="homework_id.lesson_label", string="Dars", readonly=True)
    task_assigned_datetime = fields.Datetime(
        related="homework_id.assigned_datetime", string="Vazifa berilgan vaqt",
        readonly=True)
    task_due_date = fields.Date(
        related="homework_id.due_date", string="Deadline", readonly=True)

    # XP (gamification karma) bookkeeping: award once when the homework is passed.
    xp_awarded = fields.Boolean(string="XP Awarded", default=False, copy=False, readonly=True)
    xp_amount = fields.Integer(string="XP Awarded (amount)", default=0, copy=False, readonly=True)

    # -------------------------
    # Access
    # -------------------------
    def _check_student_access(self):
        user = self.env.user
        if user._is_admin():
            return
        if any(s.user_id != user for s in self):
            raise AccessError(_("You can only see your own submissions."))

    # -------------------------
    # Helpers
    # -------------------------
    def _state_from_mark(self, mark, pass_mark):
        """Calculate state based on mark and pass_mark"""
        if mark is False or mark is None:
            return "submitted"
        if pass_mark is False or pass_mark is None:
            return "graded"
        return "graded" if mark >= pass_mark else "failed"

    def _award_xp(self):
        """Keep gamification XP (karma) in sync with the submission mark.

        XP mirrors the mark while the submission is passed ('graded'), and is 0
        otherwise. On every (re)grade we adjust the user's karma by the delta
        against what was previously awarded (tracked in ``xp_amount``), so
        updating the ball updates the XP, and dropping below the pass mark
        removes it. Karma is never pushed below 0.

        NB: gamification.karma.tracking.origin_ref is a Reference whose selection
        only allows registered models (res.users by default); edu.homework is not
        one, so we pass the homework name via ``reason`` rather than as origin."""
        for rec in self:
            user = rec.user_id
            if not user:
                continue
            target = int(round(rec.mark or 0.0)) if rec.state == "graded" else 0
            if target < 0:
                target = 0
            delta = target - (rec.xp_amount or 0)
            if delta == 0:
                continue
            if delta < 0:
                delta = max(delta, -user.karma)  # never push karma below 0
            if delta:
                reason = _("Homework XP: %s") % (rec.homework_id.name or rec.homework_id.id)
                user.sudo()._add_karma(delta, reason=reason)
            rec.xp_amount = target
            rec.xp_awarded = bool(target)

    # -------------------------
    # Create / Write
    # -------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "mark" in vals:
                homework = self.env["edu.homework"].browse(vals.get("homework_id"))
                pass_mark = homework.pass_mark if homework else False
                vals["state"] = self._state_from_mark(vals.get("mark"), pass_mark)
            # Attempt bookkeeping. A submission for a (homework, student) pair
            # that already has one is a RESUBMISSION: it gets its own ordinal
            # and, when it arrives ungraded, the dedicated 'resubmitted' state
            # so the teacher sees the retry instead of the previous attempt's
            # verdict. sudo: numbering must not depend on the record rules of
            # whoever creates the row (student on the website, teacher grading
            # on a student's behalf).
            prior = 0
            if vals.get("homework_id") and vals.get("student_id"):
                prior = self.sudo().search_count([
                    ("homework_id", "=", vals["homework_id"]),
                    ("student_id", "=", vals["student_id"]),
                ])
            vals.setdefault("attempt_no", prior + 1)
            if prior and vals.get("state", "submitted") == "submitted":
                vals["state"] = "resubmitted"
        records = super().create(vals_list)
        records._award_xp()
        return records

    def write(self, vals):
        if "mark" in vals:
            for rec in self:
                mark = vals.get("mark")
                pass_mark = rec.homework_id.pass_mark
                new_state = self._state_from_mark(mark, pass_mark)
                update_vals = dict(vals, state=new_state)
                super(EduHomeworkSubmission, rec).write(update_vals)

                # Re-sync XP (karma) with the new mark/state on every grade,
                # so updating the ball updates the XP (and failing removes it).
                rec._award_xp()

                # Auto-complete slide when homework passed
                if new_state == "graded" and rec.homework_id.slide_id:
                    slide = rec.homework_id.slide_id
                    partner = rec.student_id
                    channel_partner = self.env['slide.channel.partner'].sudo().search([
                        ('channel_id', '=', slide.channel_id.id),
                        ('partner_id', '=', partner.id),
                    ], limit=1)
                    if channel_partner:
                        self.env['slide.slide.partner'].sudo().search([
                            ('slide_id', '=', slide.id),
                            ('partner_id', '=', partner.id),
                        ]).write({'completed': True}) or self.env['slide.slide.partner'].sudo().create({
                            'slide_id': slide.id,
                            'partner_id': partner.id,
                            'completed': True,
                        })
            return True
        return super().write(vals)

    # -------------------------
    # Grading dialog
    # -------------------------
    def action_open_grading(self):
        """Open the one-screen grading dialog for this submission's student.

        Lets a teacher grade straight from any submission list (Marks menu,
        Dars vazifasi roster) without drilling into the submission form."""
        self.ensure_one()
        if not self.student_id:
            raise UserError(_("Bu topshiriqda o'quvchi ko'rsatilmagan."))
        return self.env["edu.homework.grade.wizard"].open_grading(
            student=self.student_id,
            homework=self.homework_id,
        )