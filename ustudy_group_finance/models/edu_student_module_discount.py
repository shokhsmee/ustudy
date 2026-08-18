# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EduStudentModuleDiscount(models.Model):
    """Per-student, per-group-module discount (chegirma).

    Each record says: for THIS enrollment (student in a group) and THIS module,
    the student pays `module_price - discount_amount`. The discount is treated
    as a virtual payment everywhere the module price is compared against
    payments (payment wizard, cc.finance confirm, carry-forward, lesson
    payment stats), so the student only owes the remaining sum.
    """
    _name = "edu.student.module.discount"
    _description = "Student Module Discount (Chegirma)"
    _order = "student_id, module_sequence asc, id asc"

    student_id = fields.Many2one(
        "res.partner",
        string="Talaba",
        required=True,
        ondelete="cascade",
        index=True,
        domain="[('is_student', '=', True)]",
    )

    student_line_id = fields.Many2one(
        "edu.group.student",
        string="Guruh a'zoligi",
        required=True,
        ondelete="cascade",
        index=True,
        domain="[('student_id', '=', student_id), ('state', '!=', 'cancelled')]",
    )

    group_id = fields.Many2one(
        "edu.group",
        string="Guruh",
        related="student_line_id.group_id",
        store=True,
        readonly=True,
    )

    module_id = fields.Many2one(
        "edu.module",
        string="Modul",
        required=True,
        ondelete="restrict",
        domain="[('active', '=', True)]",
    )

    module_sequence = fields.Integer(
        related="module_id.sequence",
        store=True,
        readonly=True,
    )

    company_id = fields.Many2one(
        "res.company",
        related="student_line_id.company_id",
        store=True,
        readonly=True,
    )

    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
    )

    module_price = fields.Float(
        string="Modul narxi",
        compute="_compute_prices",
        help="Full module price from the education configuration.",
    )

    discount_amount = fields.Float(
        string="Chegirma",
        required=True,
        help="Discount amount (so'm) off the module price for this student "
             "in this group module.",
    )

    final_price = fields.Float(
        string="To'lanadigan summa",
        compute="_compute_prices",
        help="Module price minus the discount — what the student actually owes "
             "for this module.",
    )

    note = fields.Char(string="Izoh")

    # Odoo 19 constraint API (old-style _sql_constraints lists are ignored)
    _student_line_module_unique = models.Constraint(
        "unique(student_line_id, module_id)",
        "Bu guruh moduli uchun chegirma allaqachon belgilangan.",
    )

    @api.depends("discount_amount", "student_line_id")
    def _compute_prices(self):
        config = self.env["edu.config"].get_config()
        price = config.module_price or 0.0
        for rec in self:
            rec.module_price = price
            rec.final_price = max(0.0, price - rec.discount_amount)

    def _compute_display_name(self):
        for rec in self:
            parts = [rec.student_id.name or "", rec.module_id.name or ""]
            rec.display_name = " – ".join(p for p in parts if p)

    @api.constrains("discount_amount")
    def _check_discount_amount(self):
        config = self.env["edu.config"].get_config()
        price = config.module_price or 0.0
        for rec in self:
            if rec.discount_amount <= 0:
                raise ValidationError(_("Chegirma summasi 0 dan katta bo'lishi kerak."))
            if price and rec.discount_amount > price:
                raise ValidationError(_(
                    "Chegirma (%(discount)s) modul narxidan (%(price)s) oshib ketmasligi kerak.",
                    discount="{:,.0f}".format(rec.discount_amount),
                    price="{:,.0f}".format(price),
                ))

    @api.constrains("student_id", "student_line_id")
    def _check_student_line_matches(self):
        for rec in self:
            if (
                rec.student_id
                and rec.student_line_id
                and rec.student_line_id.student_id != rec.student_id
            ):
                raise ValidationError(_(
                    "Tanlangan guruh a'zoligi bu talabaga tegishli emas."
                ))

    @api.onchange("student_line_id")
    def _onchange_student_line_id(self):
        for rec in self:
            if rec.student_line_id and not rec.student_id:
                rec.student_id = rec.student_line_id.student_id
            if rec.student_line_id and not rec.module_id:
                rec.module_id = rec.student_line_id.current_module_id

    # ------------------------------------------------------------------
    # Audit trail: log every discount change to the group chatter, the same
    # place module payments are already logged.
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Keep student_id coherent when lines are created from the
            # enrollment side (e.g. imports) without an explicit student.
            if vals.get("student_line_id") and not vals.get("student_id"):
                line = self.env["edu.group.student"].browse(vals["student_line_id"])
                vals["student_id"] = line.student_id.id
        records = super().create(vals_list)
        records._log_discount(_("💸 Chegirma belgilandi"))
        return records

    def write(self, vals):
        res = super().write(vals)
        if "discount_amount" in vals or "module_id" in vals:
            self._log_discount(_("✏️ Chegirma o'zgartirildi"))
        return res

    def unlink(self):
        self._log_discount(_("🗑️ Chegirma bekor qilindi"))
        return super().unlink()

    def _log_discount(self, title):
        for rec in self:
            if not rec.group_id:
                continue
            rec.group_id.message_post(body="%s: %s — %s — %s so'm" % (
                title,
                rec.student_id.name or "",
                rec.module_id.name or "",
                "{:,.0f}".format(rec.discount_amount),
            ))
