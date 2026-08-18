from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .edu_homework_submission import UNGRADED_STATES


class EduHomeworkGradeWizard(models.TransientModel):
    """One-screen grading dialog.

    Grading used to mean drilling down three levels: the timetable Vazifalar
    roster -> "Baholash" (submissions list) -> the submission form, for every
    single student. This wizard collapses that into one dialog opened straight
    from a roster row: the student's LATEST submission (date, attempt number,
    status, izoh, files) is shown next to the Ball/Izoh inputs, with every
    earlier attempt listed underneath. "Saqlash va keyingisi" jumps to the next
    student still waiting for a ball, so a whole lesson is graded without ever
    leaving the dialog."""

    _name = "edu.homework.grade.wizard"
    _description = "Vazifani baholash (tez oyna)"

    # --- context -----------------------------------------------------------
    student_id = fields.Many2one("res.partner", string="O'quvchi", readonly=True)
    homework_id = fields.Many2one("edu.homework", string="Vazifa", readonly=True)
    # Opened from the timetable Vazifalar roster. The roster row itself cannot
    # be stored in a many2one — edu.student.lesson.report ids are synthetic
    # bigints (timetable * 1e6 + student), way past int4 — so the row is
    # re-derived from (timetable, student) whenever it is needed: to save
    # through its write() (which attaches a homework to a slide-only lesson)
    # and to walk to the next student of the same lesson.
    from_roster = fields.Boolean(readonly=True)
    timetable_id = fields.Many2one(
        "edu.timetable", string="Dars (jadval)", readonly=True)
    lesson_label = fields.Char(string="Dars", readonly=True)

    # --- the student's latest attempt --------------------------------------
    submission_id = fields.Many2one(
        "edu.homework.submission", string="Oxirgi topshiriq", readonly=True)
    submission_state = fields.Selection(
        related="submission_id.state", string="Holati", readonly=True)
    submit_date = fields.Datetime(string="Topshirilgan vaqt", readonly=True)
    attempt_no = fields.Integer(string="Urinish №", readonly=True)
    attempt_total = fields.Integer(string="Jami urinishlar", readonly=True)
    is_resubmission = fields.Boolean(string="Qayta topshirilgan", readonly=True)
    has_submission = fields.Boolean(string="Topshirgan", readonly=True)
    student_comment = fields.Text(string="O'quvchi izohi", readonly=True)
    student_attachment_ids = fields.Many2many(
        "ir.attachment",
        "edu_grade_wizard_attachment_rel", "wizard_id", "attachment_id",
        string="Yuklangan fayllar", readonly=True)
    attempt_ids = fields.Many2many(
        "edu.homework.submission",
        "edu_grade_wizard_attempt_rel", "wizard_id", "submission_id",
        string="Barcha urinishlar", readonly=True)

    # --- grading -----------------------------------------------------------
    pass_mark = fields.Float(string="O'tish bali", readonly=True)
    mark = fields.Float(string="Ball")
    teacher_comment = fields.Text(string="O'qituvchi izohi")

    # -----------------------------------------------------------------
    # Opening
    # -----------------------------------------------------------------
    @api.model
    def open_grading(self, student, homework=False, report=False):
        """Build the dialog for one (student, homework) pair and return its
        act_window. ``homework`` may be empty (lesson without a task yet): the
        ball is then persisted through ``report``, which attaches one."""
        if not student:
            raise UserError(_("O'quvchi topilmadi."))
        Submission = self.env["edu.homework.submission"]
        attempts = Submission.browse()
        if homework:
            attempts = Submission.search(
                [("homework_id", "=", homework.id), ("student_id", "=", student.id)],
                order="submit_date desc, id desc",
            )
        last = attempts[:1]
        timetable = report.timetable_id if report else (
            homework.timetable_id if homework else False)
        wizard = self.create({
            "student_id": student.id,
            "homework_id": homework.id if homework else False,
            "from_roster": bool(report),
            "timetable_id": timetable.id if timetable else False,
            "lesson_label": (homework.lesson_label if homework else False)
                            or (timetable.name if timetable else False),
            "submission_id": last.id,
            "submit_date": last.submit_date,
            "attempt_no": last.attempt_no or (len(attempts) if last else 0),
            "attempt_total": len(attempts),
            "is_resubmission": len(attempts) > 1,
            "has_submission": bool(last),
            "student_comment": last.comment,
            "student_attachment_ids": [(6, 0, last.attachment_ids.ids)],
            "attempt_ids": [(6, 0, attempts.ids)],
            "pass_mark": homework.pass_mark if homework else 0.0,
            "mark": last.mark,
            "teacher_comment": last.teacher_comment,
        })
        return wizard._action_open()

    def _action_open(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Baholash — %s") % (self.student_id.display_name or ""),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(self.env.ref(
                "ustudy_homework.view_edu_homework_grade_wizard_form").id, "form")],
            "target": "new",
        }

    # -----------------------------------------------------------------
    # Saving
    # -----------------------------------------------------------------
    def _roster_row(self):
        """This dialog's row in the lesson roster, re-derived from (lesson,
        student) — see ``from_roster`` for why it isn't stored."""
        self.ensure_one()
        if not self.from_roster or not self.timetable_id or not self.student_id:
            return self.env["edu.student.lesson.report"]
        return self.env["edu.student.lesson.report"].search([
            ("timetable_id", "=", self.timetable_id.id),
            ("student_id", "=", self.student_id.id),
        ], limit=1)

    def _save_grade(self):
        """Persist Ball/Izoh on the student's latest submission.

        Three routes, in order: the submission this dialog was opened on; the
        roster row (its write() creates the homework and/or the submission when
        the student never submitted); a bare homework (grading from a
        submission list). Submission.write()/create() do the rest — state from
        the ball, XP, slide completion."""
        self.ensure_one()
        vals = {"mark": self.mark, "teacher_comment": self.teacher_comment or False}
        row = self._roster_row()
        if self.submission_id:
            self.submission_id.write(vals)
        elif row:
            row.write(vals)
        elif self.homework_id and self.student_id:
            user = self.student_id.user_ids[:1]
            self.env["edu.homework.submission"].create(dict(
                vals,
                homework_id=self.homework_id.id,
                student_id=self.student_id.id,
                user_id=user.id if user else self.env.user.id,
            ))
        else:
            raise UserError(_(
                "Ballni saqlash uchun bu darsga vazifa biriktirilishi kerak."))

    def action_save(self):
        self._save_grade()
        return {"type": "ir.actions.act_window_close"}

    def action_save_next(self):
        """Save and hop straight to the next student of the same lesson who is
        still waiting for a ball (wrapping around once). Closes when the whole
        roster is graded."""
        self._save_grade()
        nxt = self._next_pending_row()
        if not nxt:
            return {"type": "ir.actions.act_window_close"}
        return self.env[self._name].open_grading(
            student=nxt.student_id, homework=nxt.homework_id, report=nxt)

    def action_open_submission_form(self):
        """Escape hatch: the raw submission record, for attachments/chatter."""
        self.ensure_one()
        if not self.submission_id:
            raise UserError(_("Bu o'quvchi hali vazifa topshirmagan."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Topshiriq"),
            "res_model": "edu.homework.submission",
            "res_id": self.submission_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def _next_pending_row(self):
        self.ensure_one()
        if not self.from_roster or not self.timetable_id:
            return False
        rows = self.env["edu.student.lesson.report"].search(
            [("timetable_id", "=", self.timetable_id.id)])
        rows = rows.sorted(key=lambda r: (r.student_id.display_name or "").lower())
        students = [row.student_id.id for row in rows]
        if self.student_id.id in students:
            start = students.index(self.student_id.id) + 1
            rows = rows[start:] + rows[:start - 1]   # forward, then wrap around
        pending = rows.filtered(
            lambda r: r.homework_state in ("not_submitted",) + UNGRADED_STATES)
        return pending[:1] or False
