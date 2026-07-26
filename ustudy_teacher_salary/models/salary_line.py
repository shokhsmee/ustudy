# -*- coding: utf-8 -*-
from odoo import models, fields, api, _, SUPERUSER_ID


class TeacherSalaryLine(models.Model):
    """One immutable salary transaction per confirmed lesson (davomat).

    All meaningful data is snapshotted at creation time (group name, lesson
    number, module name, teacher, roster, rate and total). Later changes to
    the group / enrollment do NOT rewrite past transactions — this is the core
    requirement: lesson 45's amount stays fixed even after students leave.
    """
    _name = "edu.teacher.salary.line"
    _description = "Ustoz oyligi tranzaksiyasi"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Tr. raqami", required=True, copy=False, readonly=True,
        default="New",
    )
    date = fields.Datetime(
        string="Sana", required=True, index=True,
        default=fields.Datetime.now,
    )

    # --- source links (kept for traceability; may become empty if source deleted) ---
    attendance_id = fields.Many2one(
        "edu.attendance", string="Davomat", ondelete="set null", index=True, copy=False,
    )
    timetable_id = fields.Many2one(
        "edu.timetable", string="Dars (jadval)", ondelete="set null",
    )
    teacher_id = fields.Many2one(
        "hr.employee", string="Ustoz", required=True, index=True,
    )
    group_id = fields.Many2one("edu.group", string="Guruh", ondelete="set null")
    module_id = fields.Many2one("edu.module", string="Modul", ondelete="set null")
    tier_id = fields.Many2one("edu.teacher.salary.tier", string="Daraja", ondelete="set null")

    # --- snapshotted labels (survive deletion / rename of the source) ---
    group_name = fields.Char(string="Guruh nomi")
    teacher_name = fields.Char(string="Ustoz ismi")
    module_name = fields.Char(string="Dars moduli")
    category_name = fields.Char(string="Toifa")
    tier_name = fields.Char(string="Daraja nomi")
    lesson_no = fields.Integer(string="Dars raqami")

    # --- money snapshot ---
    percentage = fields.Float(string="Foiz (%)")
    amount_per_student = fields.Monetary(
        string="1 o'quvchi summasi", currency_field="currency_id",
    )
    student_count = fields.Integer(string="Aktiv o'quvchilar")
    amount_total = fields.Monetary(
        string="Summa", currency_field="currency_id", tracking=True,
    )
    transaction_type = fields.Selection(
        [("kirim", "Kirim"), ("chiqim", "Chiqim")],
        string="Traz. turi", default="kirim", required=True,
    )

    student_line_ids = fields.One2many(
        "edu.teacher.salary.line.student", "salary_line_id",
        string="O'quvchilar ro'yxati",
    )

    state = fields.Selection(
        [("draft", "Qoralama"), ("confirmed", "Tasdiqlangan"), ("cancelled", "Bekor qilingan")],
        string="Holat", default="confirmed", required=True, tracking=True,
    )
    cc_finance_id = fields.Many2one(
        "cc.finance", string="Chiqim yozuvi", ondelete="set null", copy=False,
        help="Ushbu oylik uchun Chiqimlarga yozilgan moliyaviy yozuv.",
    )
    note = fields.Text(string="Izoh")

    company_id = fields.Many2one(
        "res.company", string="Kompaniya",
        default=lambda self: self.env.company, required=True, index=True,
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id",
        string="Valyuta", readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "edu.teacher.salary.line"
                ) or "New"
        records = super().create(vals_list)
        for rec in records:
            # manual creations may skip the snapshot labels — fill them so the
            # record survives later renames/deletions like auto-created ones
            fix = {}
            if rec.teacher_id and not rec.teacher_name:
                fix["teacher_name"] = rec.teacher_id.name
            if rec.group_id and not rec.group_name:
                fix["group_name"] = rec.group_id.name
            if rec.module_id and not rec.module_name:
                fix["module_name"] = rec.module_id.name
            if fix:
                super(TeacherSalaryLine, rec).write(fix)
            # hook the attendance back to this transaction so the timetable
            # board (salary_state) treats manual transactions like auto ones
            att = rec.attendance_id
            if (rec.transaction_type == "kirim" and att
                    and (not att.salary_line_id
                         or att.salary_line_id.state == "cancelled")):
                att.sudo().write({"salary_line_id": rec.id})
        return records

    # ------------------------------------------------------------------
    # Manual creation from a timetable lesson (old/missed lessons)
    # ------------------------------------------------------------------
    @api.onchange("timetable_id")
    def _onchange_timetable_id(self):
        """Picking a lesson auto-fills everything the davomat-confirm flow
        would have snapshotted: date, teacher, group, module, lesson number,
        the teacher's tier rate and the group's active students roster."""
        for rec in self:
            tt = rec.timetable_id
            if not tt:
                continue
            teacher = tt.teacher_id
            attendance = tt.attendance_ids.filtered(
                lambda a: a.state == "confirmed"
            )[:1] or tt.attendance_ids[:1]

            rec.date = tt.start_datetime
            rec.attendance_id = attendance.id if attendance else False
            rec.teacher_id = teacher.id if teacher else False
            rec.teacher_name = teacher.name if teacher else ""
            rec.group_id = tt.group_id.id if tt.group_id else False
            rec.group_name = tt.group_id.name if tt.group_id else ""
            rec.module_id = tt.module_id.id if tt.module_id else False
            rec.module_name = tt.module_id.name if tt.module_id else ""
            rec.lesson_no = tt.lesson_sequence or 0

            tier = teacher.sudo().salary_tier_id if teacher else False
            rate = tier.amount_per_student if tier else 0.0
            rec.tier_id = tier.id if tier else False
            rec.tier_name = tier.name if tier else ""
            rec.category_name = tier.category_id.name if tier and tier.category_id else ""
            rec.percentage = tier.percentage if tier else 0.0
            rec.amount_per_student = rate

            # roster: every active student of the group; status comes from the
            # lesson's davomat when it exists, otherwise "Bor" (an old lesson
            # created manually is paid as held)
            status_by_student = {}
            if attendance:
                for al in attendance.attendance_line_ids:
                    status_by_student.setdefault(al.student_id.id, al.status)
            default_status = "absent" if attendance else "present"
            seen, commands = set(), [(5, 0, 0)]
            for sl in tt.group_id.student_line_ids.filtered(
                lambda s: s.state == "active"
            ):
                student = sl.student_id
                if not student or student.id in seen:
                    continue
                seen.add(student.id)
                commands.append((0, 0, {
                    "student_id": student.id,
                    "student_name": student.name,
                    "status": status_by_student.get(student.id, default_status),
                    "amount": rate,
                }))
            rec.student_line_ids = commands
            if rec.transaction_type == "kirim":
                rec.student_count = len(seen)
                rec.amount_total = rate * len(seen)

        # duplicate guard: warn (don't block) if this lesson already has a
        # confirmed earning transaction
        tt = self.timetable_id
        if tt:
            dup = self.env["edu.teacher.salary.line"].search([
                ("timetable_id", "=", tt.id),
                ("transaction_type", "=", "kirim"),
                ("state", "=", "confirmed"),
                ("id", "!=", self._origin.id or False),
            ], limit=1)
            if dup:
                return {"warning": {
                    "title": _("Diqqat: takroriy tranzaksiya"),
                    "message": _(
                        "Ushbu dars uchun tasdiqlangan oylik tranzaksiyasi "
                        "allaqachon mavjud: %s. Yangi tranzaksiya yaratsangiz, "
                        "ustozga ikki marta hisoblanadi."
                    ) % dup.name,
                }}

    @api.onchange("teacher_id")
    def _onchange_teacher_id(self):
        """The teacher drives the (teacher-filtered) lesson picker. On a new
        record, switching teacher invalidates a previously picked lesson and
        everything it auto-filled; on saved records only refresh the name and
        fill the tier when it was never set (teacher corrections must not
        rewrite an old snapshot)."""
        for rec in self:
            if not rec.teacher_id:
                continue
            rec.teacher_name = rec.teacher_id.name
            is_new = not rec._origin.id
            if (is_new and rec.timetable_id
                    and rec.timetable_id.teacher_id != rec.teacher_id):
                rec.timetable_id = False
                rec.attendance_id = False
                rec.group_id = False
                rec.group_name = ""
                rec.module_id = False
                rec.module_name = ""
                rec.lesson_no = 0
                rec.student_line_ids = [(5, 0, 0)]
                rec.student_count = 0
                rec.amount_total = 0.0
            tier = rec.teacher_id.sudo().salary_tier_id
            if tier and (is_new or (not rec.tier_id and not rec.amount_per_student)):
                rec.tier_id = tier.id
                rec.tier_name = tier.name
                rec.category_name = tier.category_id.name if tier.category_id else ""
                rec.percentage = tier.percentage
                rec.amount_per_student = tier.amount_per_student

    @api.onchange("student_line_ids")
    def _onchange_student_line_ids(self):
        """Live-update the count/total in the form as the roster is edited
        (earning transactions only). Only NON-removed students count.
        Persisted + logged in write()."""
        for rec in self:
            if rec.transaction_type == "kirim":
                count = len(rec.student_line_ids.filtered(lambda s: not s.has_removed))
                rec.student_count = count
                rec.amount_total = rec.amount_per_student * count

    def _active_student_count(self):
        self.ensure_one()
        return len(self.student_line_ids.filtered(lambda s: not s.has_removed))

    def _recompute_amounts(self):
        """Set student_count/amount_total from the non-removed roster."""
        for rec in self:
            if rec.transaction_type != "kirim":
                continue
            count = rec._active_student_count()
            total = rec.amount_per_student * count
            vals = {}
            if rec.student_count != count:
                vals["student_count"] = count
            if rec.amount_total != total:
                vals["amount_total"] = total
            if vals:
                super(TeacherSalaryLine, rec).write(vals)

    def _log_toggle(self, student_name, removed, old_total):
        self.ensure_one()
        self.message_post(body=_(
            "%(icon)s O'quvchi %(action)s (moliyaviy o'tkazma): %(name)s. "
            "Summa: %(ot)s → %(nt)s"
        ) % {
            "icon": "➖" if removed else "➕",
            "action": _("olib tashlandi") if removed else _("qayta faollashtirildi"),
            "name": student_name or "",
            "ot": "{:,.0f}".format(old_total or 0.0),
            "nt": "{:,.0f}".format(self.amount_total),
        })

    def write(self, vals):
        track = "student_line_ids" in vals
        snapshot = {}
        if track:
            for rec in self:
                snapshot[rec.id] = {
                    "ids": set(rec.student_line_ids.mapped("student_id").ids),
                    "names": {
                        s.student_id.id: (s.student_name or (s.student_id.name or ""))
                        for s in rec.student_line_ids
                    },
                    "count": rec.student_count,
                    "total": rec.amount_total,
                }
        res = super().write(vals)
        if track:
            for rec in self:
                if rec.transaction_type != "kirim":
                    continue
                # normalise newly added rows (name + per-student amount)
                for child in rec.student_line_ids:
                    fix = {}
                    if not child.student_name and child.student_id:
                        fix["student_name"] = child.student_id.name
                    if not child.amount:
                        fix["amount"] = rec.amount_per_student
                    if not child.status:
                        fix["status"] = "present"
                    if fix:
                        child.write(fix)
                new_count = rec._active_student_count()
                new_total = rec.amount_per_student * new_count
                if rec.student_count != new_count or rec.amount_total != new_total:
                    # bypass this override (no student_line_ids in vals) — no recursion
                    super(TeacherSalaryLine, rec).write({
                        "student_count": new_count,
                        "amount_total": new_total,
                    })
                snap = snapshot.get(rec.id)
                if snap:
                    new_ids = set(rec.student_line_ids.mapped("student_id").ids)
                    added = new_ids - snap["ids"]
                    removed = snap["ids"] - new_ids
                    if added or removed or snap["count"] != new_count:
                        rec._log_roster_change(added, removed, snap, new_count, new_total)
        return res

    def _log_roster_change(self, added, removed, snap, new_count, new_total):
        self.ensure_one()
        cur_names = {
            s.student_id.id: (s.student_name or (s.student_id.name or ""))
            for s in self.student_line_ids
        }
        parts = [_("✏️ O'quvchilar ro'yxati o'zgartirildi (moliyaviy o'tkazma)")]
        if added:
            parts.append(_("➕ Qo'shildi: %s") % ", ".join(
                cur_names.get(i, str(i)) for i in added))
        if removed:
            parts.append(_("➖ Olib tashlandi: %s") % ", ".join(
                snap["names"].get(i, str(i)) for i in removed))
        parts.append(_("O'quvchilar soni: %(oc)s → %(nc)s") % {
            "oc": snap["count"], "nc": new_count})
        parts.append(_("Summa: %(ot)s → %(nt)s") % {
            "ot": "{:,.0f}".format(snap["total"]),
            "nt": "{:,.0f}".format(new_total),
        })
        self.message_post(body="\n".join(parts))

    def action_cancel(self):
        for rec in self:
            rec.state = "cancelled"
        return True

    def action_set_confirmed(self):
        for rec in self:
            rec.state = "confirmed"
        return True

    def _post_expense(self, method=False):
        """Post the real company expense (Chiqim) for a salary PAYMENT.

        Only payment lines (transaction_type='chiqim') hit Chiqimlar — per
        lesson earnings (kirim) never do. This keeps the books on a cash basis:
        the expense is recognised when the teacher is actually paid, not when
        they earn. Returns the created (or existing) cc.finance record.
        """
        self.ensure_one()
        if self.cc_finance_id or self.transaction_type != "chiqim" or self.amount_total <= 0:
            return self.cc_finance_id
        icp = self.env["ir.config_parameter"].sudo()
        env = self.env["cc.finance"].with_user(SUPERUSER_ID)

        ptype = env.env["cc.payment.type"].search([("code", "=", "teacher_salary")], limit=1)
        if not ptype:
            ptype = env.env["cc.payment.type"].create({
                "name": "O'qituvchi Oyligi",
                "code": "teacher_salary",
                "direction": "chiqim",
                "type_category": "teacher",
            })
        elif not ptype.direction:
            ptype.write({"direction": "chiqim"})

        if not method:
            method_id = icp.get_param("ustudy_teacher_salary.default_method_id")
            if method_id:
                method = env.env["cc.payment.method"].browse(int(method_id)).exists()
        if not method:
            method = env.env["cc.payment.method"].search([("code", "=", "cash")], limit=1)
        if not method:
            method = env.env["cc.payment.method"].search([], limit=1)
        if not method:
            method = env.env["cc.payment.method"].create({"name": "Cash", "code": "cash"})

        finance = env.create({
            "date": self.date.date() if self.date else fields.Date.context_today(self),
            "transaction_type": "expense",
            "employee_id": self.teacher_id.id,
            "payment_method_id": method.id,
            "payment_type_id": ptype.id,
            "amount": self.amount_total,
            "description": self.note or (_("Ustoz oyligi to'lovi: %s") % (self.teacher_name or "")),
            "state": "confirmed",
            "company_id": self.company_id.id,
        })
        self.cc_finance_id = finance.id
        return finance


class TeacherSalaryLineStudent(models.Model):
    """Snapshot of the students that made a given lesson's salary count."""
    _name = "edu.teacher.salary.line.student"
    _description = "Ustoz oyligi tranzaksiyasi - o'quvchi"

    salary_line_id = fields.Many2one(
        "edu.teacher.salary.line", string="Tranzaksiya",
        required=True, ondelete="cascade", index=True,
    )
    student_id = fields.Many2one("res.partner", string="O'quvchi", ondelete="set null")
    student_name = fields.Char(string="O'quvchi ismi")
    status = fields.Selection(
        [("present", "Bor"), ("absent", "Yo'q")], string="Davomat",
    )
    amount = fields.Monetary(string="Summa", currency_field="currency_id")
    has_removed = fields.Boolean(
        string="Olib tashlangan", default=False,
        help="Belgilansa, o'quvchi oylik hisobidan chiqariladi va summa kamayadi.",
    )
    currency_id = fields.Many2one(related="salary_line_id.currency_id", readonly=True)

    def _set_removed(self, removed):
        """Flip has_removed here and mirror it onto the matching attendance
        line (kept in sync between the two sections)."""
        for rec in self:
            if rec.has_removed != removed:
                rec.has_removed = removed
            att = rec.salary_line_id.attendance_id
            if att and rec.student_id:
                al = att.attendance_line_ids.filtered(
                    lambda l: l.student_id == rec.student_id
                )
                if al and al[0].has_removed != removed:
                    al.write({"has_removed": removed})

    def action_remove(self):
        lines = self.mapped("salary_line_id")
        old = {l.id: l.amount_total for l in lines}
        self._set_removed(True)
        lines._recompute_amounts()
        for rec in self:
            rec.salary_line_id._log_toggle(
                rec.student_name or (rec.student_id.name or ""), True,
                old.get(rec.salary_line_id.id),
            )
        return True

    def action_activate(self):
        lines = self.mapped("salary_line_id")
        old = {l.id: l.amount_total for l in lines}
        self._set_removed(False)
        lines._recompute_amounts()
        for rec in self:
            rec.salary_line_id._log_toggle(
                rec.student_name or (rec.student_id.name or ""), False,
                old.get(rec.salary_line_id.id),
            )
        return True

    @api.onchange("student_id")
    def _onchange_student_id(self):
        if self.student_id:
            self.student_name = self.student_id.name
            if not self.status:
                self.status = "present"
            if not self.amount and self.salary_line_id:
                self.amount = self.salary_line_id.amount_per_student
