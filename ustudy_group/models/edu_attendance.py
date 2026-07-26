from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from datetime import timedelta

from .edu_group import teacher_locked


class EduAttendance(models.Model):
    _name = "edu.attendance"
    _description = "Lesson Attendance"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "attendance_date desc"

    name = fields.Char(string="Attendance", compute="_compute_name", store=True)
    
    timetable_id = fields.Many2one(
        "edu.timetable",
        string="Lesson",
        required=True,
        ondelete="cascade",
        index=True,
    )
    
    group_id = fields.Many2one(
        "edu.group",
        string="Group",
        related="timetable_id.group_id",
        store=True,
        index=True,
    )
    
    teacher_id = fields.Many2one(
        "hr.employee",
        string="Teacher",
        related="timetable_id.teacher_id",
        store=True,
        readonly=False,
    )
    
    attendance_date = fields.Date(
        string="Date",
        related="timetable_id.start_date",
        store=True,
        index=True,
    )
    
    attendance_line_ids = fields.One2many(
        "edu.attendance.line",
        "attendance_id",
        string="Student Attendance",
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='group_id.company_id',
        store=True,
        readonly=True,
        index=True
    )
    
    total_students = fields.Integer(
        string="Total Students",
        compute="_compute_attendance_stats",
        store=True,
    )
    
    present_count = fields.Integer(
        string="Present",
        compute="_compute_attendance_stats",
        store=True,
    )
    
    absent_count = fields.Integer(
        string="Absent",
        compute="_compute_attendance_stats",
        store=True,
    )
    
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
        ],
        string="Status",
        default="draft",
        tracking=True,
    )
    
    notes = fields.Text(string="Notes")
    
    teacher_start_image = fields.Binary("Teacher Start Photo", attachment=True)
    teacher_start_image_filename = fields.Char("Start Image Filename")
    teacher_end_image = fields.Binary("Teacher End Photo", attachment=True)
    teacher_end_image_filename = fields.Char("End Image Filename")

    # UI flag: True when the current user is a locked teacher (see edu_group)
    teacher_readonly = fields.Boolean(compute="_compute_teacher_readonly")

    def _compute_teacher_readonly(self):
        locked = teacher_locked(self.env)
        for rec in self:
            rec.teacher_readonly = locked

    @api.depends("timetable_id.name", "attendance_date")
    def _compute_name(self):
        for record in self:
            if record.timetable_id and record.attendance_date:
                record.name = f"{record.timetable_id.group_id.name} - {record.attendance_date}"
            else:
                record.name = "New Attendance"

    @api.depends("attendance_line_ids", "attendance_line_ids.status")
    def _compute_attendance_stats(self):
        for record in self:
            record.total_students = len(record.attendance_line_ids)
            record.present_count = len(record.attendance_line_ids.filtered(lambda l: l.status == "present"))
            record.absent_count = len(record.attendance_line_ids.filtered(lambda l: l.status == "absent"))

    def action_confirm(self):
        """Confirm the attendance - always capture the end photo first.

        Everyone, administration included, must go through the end-photo
        wizard: the end photo is the proof the lesson actually finished, so
        there is no admin bypass here anymore."""
        self.ensure_one()

        if self.state == 'confirmed':
            raise UserError(_("Attendance is already confirmed."))

        # Every user must capture the end photo before confirming.
        return {
            "name": _("Capture Teacher End Photo"),
            "type": "ir.actions.act_window",
            "res_model": "edu.camera.end.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_attendance_id": self.id},
        }

    def action_process_confirmation(self):
        """Process the attendance and payments after end photo captured"""
        for record in self:
            if record.state == 'confirmed':
                continue
            
            config = self.env['edu.config'].get_config()
            group = record.group_id
            teacher = record.teacher_id
            
            if not teacher:
                raise UserError(_("No teacher assigned to this group. Cannot process payments."))
            
            # Get or create payment method and teacher payment type
            payment_method = self.env['cc.payment.method'].search([('code', '=', 'cash')], limit=1)
            if not payment_method:
                payment_method = self.env['cc.payment.method'].create({
                    'name': 'Cash',
                    'code': 'cash',
                })
            
            teacher_payment_type = self.env['cc.payment.type'].search([
                ('code', '=', 'teacher_salary'),
                ('type_category', '=', 'teacher')
            ], limit=1)
            if not teacher_payment_type:
                teacher_payment_type = self.env['cc.payment.type'].create({
                    'name': 'Teacher Salary',
                    'code': 'teacher_salary',
                    'type_category': 'teacher',
                })
            
            present_students = []
            frozen_students = []
            total_teacher_amount = 0.0
            
            # Process each student attendance. The group advances as ONE unit:
            # absent students advance too (billing already counts held lessons
            # via passed_lessons_count regardless of presence) — otherwise each
            # absence desyncs that student's module position from the group.
            # Presence stays recorded on the attendance line itself.
            processed_student_ids = set()
            for attendance_line in record.attendance_line_ids:
                # Duplicate attendance lines for the same student (from
                # duplicated enrollment lines in old data) must count once.
                if attendance_line.student_id.id in processed_student_ids:
                    continue
                processed_student_ids.add(attendance_line.student_id.id)

                student_line = group.student_line_ids.filtered(
                    lambda s: s.student_id == attendance_line.student_id
                )
                
                if not student_line:
                    continue
                
                student_line = student_line[0]
                
                # Skip if student is frozen or cancelled
                # if student_line.state in ['frozen', 'cancelled']:
                #     frozen_students.append(student_line.student_id.name)
                #     continue
                
                
                if student_line.state == 'cancelled':
                    continue
                
                # Increment lesson count for present students
                student_line.increment_lesson_count()
                
                # Check if student should be frozen
                # if student_line.check_and_freeze_if_unpaid():
                #     frozen_students.append(student_line.student_id.name)
                # else:
                #     present_students.append(student_line.student_id.name)
            
            # Calculate teacher payment based on present active students
            if present_students:
                teacher_percentage = teacher.finance_adjustment if teacher.finance_adjustment > 0 else 30.0
                
                # Calculate per-lesson teacher payment
                # Module price / lessons per module * teacher percentage * number of present students
                per_student_per_lesson = config.module_price / config.lessons_per_module
                total_teacher_amount = per_student_per_lesson * len(present_students) * (teacher_percentage / 100.0)
                
                if total_teacher_amount > 0:
                    teacher_finance = self.env['cc.finance'].create({
                        'date': record.attendance_date,
                        'transaction_type': 'expense',
                        'employee_id': teacher.id,
                        'payment_method_id': payment_method.id,
                        'payment_type_id': teacher_payment_type.id,
                        'amount': total_teacher_amount,
                        'description': _('Teaching: %s - %s\n%d students × %s per lesson × %s%%') % (
                            group.name,
                            record.attendance_date,
                            len(present_students),
                            "{:,.0f}".format(per_student_per_lesson),
                            teacher_percentage
                        ),
                        'state': 'draft',
                    })
                    
                    teacher_finance.action_confirm()
            
            record.write({"state": "confirmed"})
            
            # Post summary message
            message_parts = [_("✅ Attendance Confirmed")]
            message_parts.append(_("Present: %d / %d students") % (record.present_count, record.total_students))
            
            if present_students:
                message_parts.append(_("Active: %s") % ", ".join(present_students))
                message_parts.append(_("Teacher payment: %s") % "{:,.2f}".format(total_teacher_amount))
            
            if frozen_students:
                message_parts.append(_("⚠️ Frozen (payment required): %s") % ", ".join(frozen_students))
            
            record.group_id.message_post(body="\n".join(message_parts))
        
    def action_reset_to_draft(self):
        """Reset to draft, reversing the lesson-count increments of confirm.

        Without the rollback, reset + re-confirm (or reset + delete) counts the
        same lesson twice / leaves phantom lessons on the students' module
        progress — this is exactly how the U18 module drift happened."""
        if teacher_locked(self.env):
            raise AccessError(_("Tasdiqlangan davomatni faqat administratsiya qaytara oladi."))
        for record in self:
            if record.state != "confirmed":
                continue
            # Mirror of action_process_confirmation: every enrolled student
            # advanced on confirm (present or absent), so every one steps back.
            processed_student_ids = set()
            for line in record.attendance_line_ids:
                if line.student_id.id in processed_student_ids:
                    continue
                processed_student_ids.add(line.student_id.id)
                student_line = record.group_id.student_line_ids.filtered(
                    lambda s: s.student_id == line.student_id and s.state != "cancelled"
                )[:1]
                if student_line:
                    student_line.decrement_lesson_count()
            record.group_id.message_post(
                body=_("↩️ Davomat qoralamaga qaytarildi (%s) — o'quvchilarning dars hisoblari qaytarildi.") % (record.attendance_date or "",)
            )
        self.write({"state": "draft"})

    def unlink(self):
        # A confirmed attendance already advanced the students' lesson counts
        # (and module payments were processed from it). Deleting it would leave
        # those increments orphaned — force an explicit reset first, which
        # rolls the counts back.
        if any(rec.state == "confirmed" for rec in self):
            raise UserError(_(
                "Tasdiqlangan davomatni o'chirish mumkin emas. Avval uni "
                "qoralamaga qaytaring — o'quvchilarning dars hisoblari "
                "avtomatik qaytariladi."
            ))
        return super().unlink()

    def write(self, vals):
        # Teachers take attendance while it is draft; once confirmed it is
        # frozen for them (payments were already processed from it).
        if teacher_locked(self.env) and any(rec.state == "confirmed" for rec in self):
            raise AccessError(_("Tasdiqlangan davomatni o'zgartirish mumkin emas. Bu administratsiya vazifasi."))
        return super().write(vals)
    
    def action_mark_all_present(self):
        """Mark all students as present"""
        self.ensure_one()
        self.attendance_line_ids.write({"status": "present"})
    
    def action_mark_all_absent(self):
        """Mark all students as absent"""
        self.ensure_one()
        self.attendance_line_ids.write({"status": "absent"})

    
    attendance_start_datetime = fields.Datetime(
        string="Start DateTime",
        compute="_compute_attendance_datetimes",
        store=True,
    )
    attendance_end_datetime = fields.Datetime(
        string="End DateTime",
        compute="_compute_attendance_datetimes",
        store=True,
    )

    @api.depends("timetable_id.start_datetime", "timetable_id.end_datetime", "attendance_date")
    def _compute_attendance_datetimes(self):
        for rec in self:
            if rec.timetable_id and rec.timetable_id.start_datetime:
                rec.attendance_start_datetime = rec.timetable_id.start_datetime
                rec.attendance_end_datetime = rec.timetable_id.end_datetime
            elif rec.attendance_date:
                from datetime import datetime, time
                rec.attendance_start_datetime = datetime.combine(rec.attendance_date, time(8, 0))
                rec.attendance_end_datetime = datetime.combine(rec.attendance_date, time(9, 30))
            else:
                rec.attendance_start_datetime = False
                rec.attendance_end_datetime = False


class EduAttendanceLine(models.Model):
    _name = "edu.attendance.line"
    _description = "Student Attendance Line"
    _order = "student_name"
    _rec_name = "display_name"

    attendance_id = fields.Many2one(
        "edu.attendance",
        string="Attendance",
        required=True,
        ondelete="cascade",
        index=True,
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='attendance_id.company_id',
        store=True,
        readonly=True,
        index=True
    )
    
    student_id = fields.Many2one(
        "res.partner",
        string="Student",
        required=True,
        domain="[('is_student','=',True),('company_id','=',company_id)]",
        index=True,
    )
    
    student_name = fields.Char(
        string="Student Name",
        related="student_id.name",
        store=True,
    )
    
    status = fields.Selection(
        [
            ("present", "Keldi (Present)"),
            ("absent", "Kelmadi (Absent)"),
        ],
        string="Status",
        default="present",
        required=True,
    )
    
    notes = fields.Text(string="Notes")
    
    
    attendance_start_datetime = fields.Datetime(
        string="Start DateTime",
        compute="_compute_attendance_datetimes",
        store=True,
    )
    attendance_end_datetime = fields.Datetime(
        string="End DateTime",
        compute="_compute_attendance_datetimes",
        store=True,
    )
    group_id = fields.Many2one(
        "edu.group",
        string="Group",
        related="attendance_id.group_id",
        store=True,
    )
    
    display_name = fields.Char(
        string="Display Name",
        compute="_compute_display_name_field",
        store=True,
    )

    # Same source of truth as the "To'lov holati" column on the group's
    # student list (debt_status: paid lessons vs passed lessons). The old
    # module-payment based payment_status showed a different, misleading
    # verdict here (e.g. "To'liq to'langan" for students the roster calls
    # Qarzdor).
    student_payment_status = fields.Selection(
        [
            ('paid', "Haqdor"),
            ('debtor', "Qarzdor"),
        ],
        string="To'lov holati",
        compute="_compute_student_payment_status",
        store=False,
    )

    @api.depends("attendance_id.group_id", "student_id")
    def _compute_student_payment_status(self):
        # Warm the batched passed/paid lesson computes for all member lines at
        # once — reading debt_status line-by-line would recompute per record.
        member_lines = self.mapped("attendance_id.group_id.student_line_ids")
        if member_lines:
            member_lines.mapped("debt_status")
        for rec in self:
            group = rec.attendance_id.group_id
            student_line = group.student_line_ids.filtered(
                lambda s: s.student_id == rec.student_id
            )
            rec.student_payment_status = student_line[0].debt_status if student_line else False

    @api.depends("status", "student_name")
    def _compute_display_name_field(self):
        for rec in self:
            if rec.status == "present":
                rec.display_name = "✅ Keldi"
            elif rec.status == "absent":
                rec.display_name = "❌ Kelmadi"
            else:
                rec.display_name = rec.student_name or ""

    @api.depends("attendance_id.timetable_id.start_datetime", "attendance_id.timetable_id.end_datetime")
    def _compute_attendance_datetimes(self):
        for rec in self:
            tt = rec.attendance_id.timetable_id
            if tt and tt.start_datetime:
                rec.attendance_start_datetime = tt.start_datetime
                rec.attendance_end_datetime = tt.end_datetime or (tt.start_datetime + timedelta(hours=1.5))
            else:
                rec.attendance_start_datetime = False
                rec.attendance_end_datetime = False
                
    _sql_constraints = [
        (
            "attendance_student_unique",
            "unique(attendance_id, student_id)",
            "Student already exists in this attendance record.",
        )
    ]

    def write(self, vals):
        # mirrors the edu.attendance guard: lines of a confirmed attendance
        # are frozen for teachers
        if teacher_locked(self.env) and any(
            line.attendance_id.state == "confirmed" for line in self
        ):
            raise AccessError(_("Tasdiqlangan davomatni o'zgartirish mumkin emas. Bu administratsiya vazifasi."))
        return super().write(vals)


# NOTE: the start-lesson wizard (edu.camera.wizard) lives in camera_wizard.py,
# which is imported after this module and is the single effective definition.


class CameraEndWizard(models.TransientModel):
    _name = 'edu.camera.end.wizard'
    _description = 'Teacher Camera Capture - End Lesson'
    
    attendance_id = fields.Many2one('edu.attendance', string='Attendance', required=True)
    teacher_image = fields.Binary("Teacher Photo")
    
    def action_capture_and_confirm(self):
        """Save end image and process confirmation.

        The end photo is required for everyone (administration included)."""
        self.ensure_one()

        if not self.teacher_image:
            raise UserError(_("Please capture teacher photo first."))

        self.attendance_id.write({
            "teacher_end_image": self.teacher_image,
            "teacher_end_image_filename": f"teacher_end_{fields.Datetime.now()}.jpg",
        })

        self.attendance_id.action_process_confirmation()

        # Matrix flow: close back to the davomat board (it reloads with the
        # now-confirmed Bor/Yo'q cells).
        if self.env.context.get("matrix_flow"):
            return {"type": "ir.actions.act_window_close"}

        return {
            "name": _("Attendance Confirmed"),
            "type": "ir.actions.act_window",
            "res_model": "edu.attendance",
            "res_id": self.attendance_id.id,
            "view_mode": "form",
            "target": "current",
        }



class EduTimetable(models.Model):
    _inherit = "edu.timetable"

    attendance_ids = fields.One2many(
        "edu.attendance",
        "timetable_id",
        string="Attendance Records",
    )

    attendance_count = fields.Integer(
        string="Attendance",
        compute="_compute_attendance_count",
        store=False,
    )

    has_attendance = fields.Boolean(
        string="Has Attendance",
        compute="_compute_has_attendance",
        store=False,
    )

    confirmed_attendance_line_ids = fields.Many2many(
        "edu.attendance.line",
        compute="_compute_confirmed_attendance_lines",
        string="Talaba Davomatlari",
        store=False,
    )

    has_confirmed_attendance = fields.Boolean(
        string="Has Confirmed Attendance",
        compute="_compute_confirmed_attendance_lines",
        store=False,
    )

    @api.depends("attendance_ids")
    def _compute_attendance_count(self):
        for record in self:
            record.attendance_count = len(record.attendance_ids)

    @api.depends("attendance_ids")
    def _compute_has_attendance(self):
        for record in self:
            record.has_attendance = bool(record.attendance_ids)

    @api.depends("attendance_ids.state", "attendance_ids.attendance_line_ids.status")
    def _compute_confirmed_attendance_lines(self):
        for record in self:
            confirmed = record.attendance_ids.filtered(lambda a: a.state == 'confirmed')
            lines = confirmed.mapped('attendance_line_ids')
            record.confirmed_attendance_line_ids = lines
            record.has_confirmed_attendance = bool(lines)

    def action_start_attendance(self):
        """Start attendance - capture teacher start photo"""
        self.ensure_one()

        if not self.slide_id:
            raise UserError(_("Darsni boshlash uchun dars mavzusini belgilang"))

        if self.attendance_ids:
            raise UserError(_("Attendance already exists for this lesson."))

        if not self.group_id.student_line_ids:
            raise UserError(_("No students in this group."))
        
        return {
            "name": _("Capture Teacher Start Photo"),
            "type": "ir.actions.act_window",
            "res_model": "edu.camera.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_timetable_id": self.id},
        }

    def action_view_attendance(self):
        """View attendance records for this lesson"""
        self.ensure_one()
        
        return {
            "name": _("Attendance - %s", self.name),
            "type": "ir.actions.act_window",
            "res_model": "edu.attendance",
            "view_mode": "list,form",
            "domain": [("timetable_id", "=", self.id)],
            "context": {"default_timetable_id": self.id},
        }