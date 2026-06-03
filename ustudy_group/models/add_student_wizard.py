from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EduGroupAddStudentWizard(models.TransientModel):
    _name = "edu.group.add.student.wizard"
    _description = "Add Student to Active Group"

    group_id = fields.Many2one(
        "edu.group",
        string="Group",
        required=True,
        readonly=True,
    )
    student_id = fields.Many2one(
        "res.partner",
        string="Student",
        required=True,
        domain="[('is_student', '=', True)]",
    )
    enrollment_date = fields.Date(
        string="Enrollment Date",
        required=True,
        default=fields.Date.today,
    )
    lessons_before_join = fields.Integer(
        string="Confirmed Lessons Before Join",
        compute="_compute_module_info",
        help="Number of confirmed lessons in this group before the enrollment date",
    )
    starting_module_id = fields.Many2one(
        "edu.module",
        string="Starting Module",
        compute="_compute_module_info",
        help="Auto-calculated module based on group progress at enrollment date",
    )
    module_lesson_offset = fields.Integer(
        string="Lessons Already Done in Starting Module",
        compute="_compute_module_info",
        help="How many lessons of the starting module were completed before this student joins",
    )

    # Mirror of group fields so the wizard view can show a clear status
    is_at_module_start = fields.Boolean(
        related="group_id.is_at_module_start",
        readonly=True,
    )
    lessons_until_next_module = fields.Integer(
        related="group_id.lessons_until_next_module",
        readonly=True,
    )

    @api.depends("group_id", "enrollment_date")
    def _compute_module_info(self):
        for rec in self:
            if not rec.group_id or not rec.enrollment_date:
                rec.lessons_before_join = 0
                rec.starting_module_id = False
                rec.module_lesson_offset = 0
                continue

            config = self.env["edu.config"].get_config()
            lessons_per_module = config.lessons_per_module or 12

            confirmed_before = self.env["edu.attendance"].search_count([
                ("group_id", "=", rec.group_id.id),
                ("attendance_date", "<", rec.enrollment_date),
                ("state", "=", "confirmed"),
            ])

            rec.lessons_before_join = confirmed_before

            # offset into full course list = group's starting lesson + lessons done so far
            course_offset = (rec.group_id.start_lesson_number or 1) - 1 + confirmed_before
            module_index = course_offset // lessons_per_module
            offset = course_offset % lessons_per_module

            module = self.env["edu.module"].search(
                [("sequence", "=", module_index + 1)], limit=1
            )
            if not module:
                module = self.env["edu.module"].search([], order="sequence asc", limit=1)

            rec.starting_module_id = module
            rec.module_lesson_offset = offset

    def action_confirm(self):
        self.ensure_one()

        # Server-side boundary guard — the UI hides the button when the group
        # isn't at a module boundary, but a hand-crafted action call could still
        # land here. Block it.
        if not self.group_id.is_at_module_start:
            raise UserError(_(
                "Bu guruhga hozir o'quvchi qo'shib bo'lmaydi. "
                "Guruh modul boshlanishida bo'lishi kerak. "
                "Keyingi modulgacha qolgan darslar: %s"
            ) % self.group_id.lessons_until_next_module)

        existing = self.env["edu.group.student"].search([
            ("group_id", "=", self.group_id.id),
            ("student_id", "=", self.student_id.id),
        ], limit=1)
        if existing:
            raise UserError(_(
                "%s allaqachon %s guruhida ro'yxatdan o'tgan."
            ) % (self.student_id.name, self.group_id.name))

        self.env["edu.group.student"].create({
            "group_id": self.group_id.id,
            "student_id": self.student_id.id,
            "enrollment_date": self.enrollment_date,
            "current_module_id": self.starting_module_id.id if self.starting_module_id else False,
            "starting_module_id": self.starting_module_id.id if self.starting_module_id else False,
            "lessons_in_current_module": 0,
            "state": "active",
        })

        # For confirmed attendances on/after enrollment_date, add absent line so teacher can correct
        past_attendances = self.env["edu.attendance"].search([
            ("group_id", "=", self.group_id.id),
            ("attendance_date", ">=", self.enrollment_date),
            ("state", "=", "confirmed"),
        ])
        for att in past_attendances:
            already_exists = self.env["edu.attendance.line"].search([
                ("attendance_id", "=", att.id),
                ("student_id", "=", self.student_id.id),
            ], limit=1)
            if not already_exists:
                self.env["edu.attendance.line"].create({
                    "attendance_id": att.id,
                    "student_id": self.student_id.id,
                    "status": "absent",
                })

        self.group_id.message_post(
            body=_("➕ %s guruhga qo'shildi. Sana: %s | Modul: %s") % (
                self.student_id.name,
                self.enrollment_date,
                self.starting_module_id.name if self.starting_module_id else "—",
            )
        )

        return {"type": "ir.actions.act_window_close"}
