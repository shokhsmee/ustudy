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

        for vals in vals_list:
            slide_id = vals.get('slide_id') or default_slide_id
            if slide_id and not vals.get('channel_id'):
                slide = self.env['slide.slide'].browse(slide_id)
                if slide and slide.channel_id:
                    vals['channel_id'] = slide.channel_id.id

        records = super(EduHomework, self).create(vals_list)

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

        if {'slide_id', 'is_published'} & set(vals):
            slides_after = self.mapped('slide_id')
            self._sync_timetable_homework_flags(extra_slides=slides_before | slides_after)
        return res

    def unlink(self):
        slides = self.mapped('slide_id')
        res = super().unlink()
        self.browse()._sync_timetable_homework_flags(extra_slides=slides)
        return res

    def _sync_timetable_homework_flags(self, extra_slides=None):
        """Recompute has_homework / homework_id on timetables whose slide matches.

        Stored compute fields on edu.timetable depend only on slide_id, so they
        don't auto-invalidate when an edu.homework is added/published/removed.
        This is the explicit invalidation hook."""
        if 'edu.timetable' not in self.env:
            return
        Timetable = self.env['edu.timetable']
        slides = self.mapped('slide_id') | (extra_slides or self.env['slide.slide'])
        if not slides:
            return
        timetables = Timetable.search([('slide_id', 'in', slides.ids)])
        if not timetables:
            return
        timetables._compute_has_homework()
        if 'homework_id' in Timetable._fields:
            timetables._compute_homework_id()

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