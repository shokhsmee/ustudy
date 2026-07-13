from odoo import api, fields, models


class DarsJadvaliLessonWizard(models.TransientModel):
    _name = "dars.jadvali.lesson.wizard"
    _description = "Dars Jadvali: group/lesson details popup"

    group_id = fields.Many2one("edu.group", string="Guruh", readonly=True)
    course_id = fields.Many2one(related="group_id.course_id", string="Fani")
    teacher_id = fields.Many2one(related="group_id.teacher_id", string="Ustozi")
    room_id = fields.Many2one(related="group_id.lesson_room", string="Xona")
    state = fields.Selection(related="group_id.state", string="Holati")
    start_date = fields.Date(related="group_id.start_date", string="Boshlanish")
    end_date = fields.Date(related="group_id.end_date", string="Tugash")
    lesson_start = fields.Float(related="group_id.lesson_start", string="Dars boshlanishi")
    lesson_end = fields.Float(related="group_id.lesson_end", string="Dars tugashi")

    lessons_reja = fields.Integer(string="Dars soni (Reja)", readonly=True)
    lessons_fakt = fields.Integer(string="Joriy dars (Fakt)", readonly=True)
    lessons_pct = fields.Char(string="Bajarilishi", compute="_compute_pcts")
    probniy = fields.Integer(string="Probniy", readonly=True)
    student_count = fields.Integer(string="O'quvchi soni (Fakt)", readonly=True)
    capacity = fields.Integer(string="Xona sig'imi (Reja)", compute="_compute_capacity")
    seats_pct = fields.Char(string="Bandlik", compute="_compute_pcts")

    timetable_ids = fields.Many2many(
        "edu.timetable",
        string="Tanlangan davr darslari",
        readonly=True,
    )

    @api.depends("room_id")
    def _compute_capacity(self):
        for rec in self:
            rec.capacity = rec.room_id.capacity or 0

    @api.depends("lessons_reja", "lessons_fakt", "student_count", "capacity")
    def _compute_pcts(self):
        for rec in self:
            rec.lessons_pct = (
                "%d%%" % round(rec.lessons_fakt * 100.0 / rec.lessons_reja)
                if rec.lessons_reja else "0%"
            )
            rec.seats_pct = (
                "%d%%" % round(rec.student_count * 100.0 / rec.capacity)
                if rec.capacity else "0%"
            )

    def action_open_group(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "edu.group",
            "res_id": self.group_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }
