# -*- coding: utf-8 -*-
from odoo import models, fields, _, SUPERUSER_ID


class EduAttendanceLine(models.Model):
    """Soft-remove flag mirrored with the salary transaction roster.

    Removing a student from the salary transaction keeps them VISIBLE here
    (flagged) with an Activate button to restore them into the transaction.
    """
    _inherit = "edu.attendance.line"

    has_removed = fields.Boolean(
        string="Oylikdan olib tashlangan", default=False,
        help="Belgilansa, ushbu o'quvchi ustoz oyligi hisobidan chiqarilgan.",
    )

    def _salary_student_line(self):
        self.ensure_one()
        sline = self.attendance_id.salary_line_id
        if not sline:
            return self.env["edu.teacher.salary.line.student"]
        return sline.student_line_ids.filtered(
            lambda s: s.student_id == self.student_id
        )

    def _apply_salary_removed(self, removed):
        for rec in self:
            if rec.has_removed != removed:
                rec.has_removed = removed
            ss = rec._salary_student_line()
            if ss:
                old_total = ss.salary_line_id.amount_total
                if ss.has_removed != removed:
                    ss.write({"has_removed": removed})
                ss.salary_line_id._recompute_amounts()
                ss.salary_line_id._log_toggle(
                    rec.student_id.name, removed, old_total
                )

    def action_salary_remove(self):
        self._apply_salary_removed(True)
        return True

    def action_salary_activate(self):
        self._apply_salary_removed(False)
        return True


class EduAttendance(models.Model):
    _inherit = "edu.attendance"

    salary_line_id = fields.Many2one(
        "edu.teacher.salary.line",
        string="Ustoz oyligi tranzaksiyasi",
        copy=False, readonly=True, ondelete="set null",
    )

    def action_process_confirmation(self):
        """After the base confirm logic runs, snapshot the teacher salary.

        The base method sets state='confirmed'. We create one immutable salary
        transaction per newly-confirmed attendance, using the count of active
        students at this moment and the teacher's configured tier rate.
        """
        res = super().action_process_confirmation()
        for record in self:
            if record.state == "confirmed" and not record.salary_line_id:
                record._create_teacher_salary_line()
        return res

    def action_reset_to_draft(self):
        """Reversing a confirmation removes its salary transaction and the linked
        Chiqim record, so a later re-confirm recomputes fresh."""
        res = super().action_reset_to_draft()
        for record in self:
            line = record.salary_line_id
            if line:
                record.salary_line_id = False
                # cancel the linked expense (created directly as confirmed, so
                # just flip state — no balance was ever adjusted)
                if line.cc_finance_id:
                    line.cc_finance_id.with_user(SUPERUSER_ID).write({"state": "cancelled"})
                line.sudo().action_cancel()
        return res

    # ------------------------------------------------------------------
    def _salary_active_students(self):
        """Return (student_count, roster) honouring the configured basis.

        roster is a list of (student_record, status) tuples snapshotted onto
        the salary transaction.
        """
        self.ensure_one()
        icp = self.env["ir.config_parameter"].sudo()
        basis = icp.get_param("ustudy_teacher_salary.active_basis", "enrolled")

        # attendance status per student for this lesson
        status_by_student = {}
        for al in self.attendance_line_ids:
            status_by_student.setdefault(al.student_id.id, al.status)

        if basis == "enrolled":
            active_lines = self.group_id.student_line_ids.filtered(
                lambda s: s.state == "active"
            )
            seen, roster = set(), []
            for sl in active_lines:
                if sl.student_id.id in seen:
                    continue
                seen.add(sl.student_id.id)
                roster.append((sl.student_id, status_by_student.get(sl.student_id.id, "absent")))
            return len(roster), roster

        # default: present attendance lines
        seen, roster = set(), []
        for al in self.attendance_line_ids:
            if al.status != "present" or al.student_id.id in seen:
                continue
            seen.add(al.student_id.id)
            roster.append((al.student_id, "present"))
        return len(roster), roster

    def _create_teacher_salary_line(self):
        self.ensure_one()
        teacher = self.teacher_id
        if not teacher:
            return

        tier = teacher.sudo().salary_tier_id
        rate = tier.amount_per_student if tier else 0.0
        student_count, roster = self._salary_active_students()

        if not tier or rate <= 0 or student_count <= 0:
            # guard: broken rows may have an empty group_id (stored related
            # drift) — message_post on the empty recordset raises
            if teacher and not tier and self.group_id:
                self.group_id.message_post(body=_(
                    "⚠️ Ustoz oyligi hisoblanmadi: %s ustoziga toifa/daraja "
                    "belgilanmagan."
                ) % teacher.name)
            return

        timetable = self.timetable_id
        module = timetable.module_id if timetable else False
        total = rate * student_count

        student_vals = [(0, 0, {
            "student_id": student.id,
            "student_name": student.name,
            "status": status,
            "amount": rate,
        }) for student, status in roster]

        salary_line = self.env["edu.teacher.salary.line"].sudo().create({
            "date": (timetable.start_datetime if timetable and timetable.start_datetime
                     else self.attendance_date),
            "attendance_id": self.id,
            "timetable_id": timetable.id if timetable else False,
            "teacher_id": teacher.id,
            "teacher_name": teacher.name,
            "group_id": self.group_id.id if self.group_id else False,
            "group_name": self.group_id.name if self.group_id else "",
            "module_id": module.id if module else False,
            "module_name": module.name if module else "",
            "lesson_no": timetable.lesson_sequence if timetable else 0,
            "tier_id": tier.id,
            "tier_name": tier.name,
            "category_name": tier.category_id.name if tier.category_id else "",
            "percentage": tier.percentage,
            "amount_per_student": rate,
            "student_count": student_count,
            "amount_total": total,
            "transaction_type": "kirim",
            "state": "confirmed",
            "student_line_ids": student_vals,
        })
        # sudo: the attendance is already confirmed at this point, and the
        # plain assignment hit edu.attendance's teacher-lock guard
        # ("Tasdiqlangan davomatni o'zgartirish mumkin emas") — aborting the
        # teacher's whole confirm flow (timetable was left completed with the
        # attendance stuck in draft). The salary-line back-link is system
        # bookkeeping, not a user edit.
        self.sudo().write({"salary_line_id": salary_line.id})

        # NOTE: no Chiqim is posted here. Confirming a lesson only accrues what
        # the teacher has EARNED (Ustozlar balansi). The company expense is
        # recognised later, when the salary is actually paid out via the
        # "Oylik berish" wizard (cash basis) — see
        # edu.teacher.salary.line._post_expense.

        if self.group_id:
            self.group_id.message_post(body=_(
                "💰 Ustoz oyligi: %(teacher)s — %(count)s o'quvchi × %(rate)s = %(total)s"
            ) % {
                "teacher": teacher.name,
                "count": student_count,
                "rate": "{:,.0f}".format(rate),
                "total": "{:,.0f}".format(total),
            })
        return salary_line
