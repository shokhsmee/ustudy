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
    date = fields.Datetime(string="Sana", required=True, index=True)

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
        return super().create(vals_list)

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
    currency_id = fields.Many2one(related="salary_line_id.currency_id", readonly=True)
