from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# Non-lesson room bookings (majlis/konsultatsiya/mehmon) are a separate model
# on purpose: edu.timetable requires a group and drives lesson numbering,
# davomat and teacher-salary flows — a group-less timetable row has already
# caused crashes before (NULL-group attendance/board rows), so bookings never
# touch it. Conflict checking is wired both ways instead (see the
# edu.timetable inherit below).
PURPOSE_LABELS = {
    "majlis": "Majlis",
    "konsultatsiya": "Konsultatsiya",
    "mehmon": "Mehmon uchun",
}


class DarsJadvaliBooking(models.Model):
    _name = "dars.jadvali.booking"
    _description = "Dars Jadvali: xona band qilish (majlis/konsultatsiya/mehmon)"
    _order = "start_datetime"

    name = fields.Char(string="Nomi", compute="_compute_name", store=True)
    purpose = fields.Selection(
        [
            ("majlis", "Majlis"),
            ("konsultatsiya", "Konsultatsiya"),
            ("mehmon", "Mehmon uchun"),
        ],
        string="Maqsad",
        required=True,
        default="majlis",
    )
    room_id = fields.Many2one(
        "edu.room", string="Xona", required=True, ondelete="restrict", index=True,
    )
    start_datetime = fields.Datetime(string="Boshlanishi", required=True, index=True)
    end_datetime = fields.Datetime(string="Tugashi", required=True)
    note = fields.Char(string="Izoh")
    user_id = fields.Many2one(
        "res.users", string="Band qilgan", default=lambda self: self.env.user,
        readonly=True,
    )

    @api.depends("purpose", "room_id", "note")
    def _compute_name(self):
        for rec in self:
            label = PURPOSE_LABELS.get(rec.purpose, rec.purpose or "")
            rec.name = "%s - %s" % (label, rec.room_id.name or "")

    @api.constrains("start_datetime", "end_datetime")
    def _check_dates(self):
        for rec in self:
            if rec.start_datetime and rec.end_datetime and rec.end_datetime <= rec.start_datetime:
                raise ValidationError(_("Tugash vaqti boshlanish vaqtidan keyin bo'lishi kerak."))

    @api.constrains("room_id", "start_datetime", "end_datetime")
    def _check_room_availability(self):
        Timetable = self.env["edu.timetable"]
        for rec in self:
            if not (rec.room_id and rec.start_datetime and rec.end_datetime):
                continue
            other = self.search(
                [
                    ("id", "!=", rec.id),
                    ("room_id", "=", rec.room_id.id),
                    ("start_datetime", "<", rec.end_datetime),
                    ("end_datetime", ">", rec.start_datetime),
                ],
                limit=1,
            )
            if other:
                raise ValidationError(_(
                    "%(room)s xonasi bu vaqtda allaqachon band: %(name)s (%(start)s - %(end)s).",
                    room=rec.room_id.name,
                    name=other.name,
                    start=fields.Datetime.context_timestamp(rec, other.start_datetime).strftime("%d.%m.%Y %H:%M"),
                    end=fields.Datetime.context_timestamp(rec, other.end_datetime).strftime("%H:%M"),
                ))
            lesson = Timetable.search(
                [
                    ("room_id", "=", rec.room_id.id),
                    ("state", "!=", "cancelled"),
                    ("group_id.active", "=", True),
                    ("start_datetime", "<", rec.end_datetime),
                    ("end_datetime", ">", rec.start_datetime),
                ],
                limit=1,
            )
            if lesson:
                raise ValidationError(_(
                    "%(room)s xonasida bu vaqtda dars bor: %(group)s (%(start)s - %(end)s).",
                    room=rec.room_id.name,
                    group=lesson.group_id.name,
                    start=fields.Datetime.context_timestamp(rec, lesson.start_datetime).strftime("%d.%m.%Y %H:%M"),
                    end=fields.Datetime.context_timestamp(rec, lesson.end_datetime).strftime("%H:%M"),
                ))

    def action_delete_booking(self):
        """Board card dialog: release the booked slot."""
        self.unlink()
        return {"type": "ir.actions.act_window_close"}


class EduTimetable(models.Model):
    _inherit = "edu.timetable"

    @api.constrains("room_id", "start_datetime", "end_datetime", "state")
    def _check_booking_availability(self):
        """Lessons can't be scheduled over a non-lesson room booking (the
        lesson-vs-lesson conflict check lives in ustudy_group)."""
        Booking = self.env["dars.jadvali.booking"]
        for rec in self:
            if not (rec.room_id and rec.start_datetime and rec.end_datetime):
                continue
            if rec.state == "cancelled":
                continue
            booking = Booking.search(
                [
                    ("room_id", "=", rec.room_id.id),
                    ("start_datetime", "<", rec.end_datetime),
                    ("end_datetime", ">", rec.start_datetime),
                ],
                limit=1,
            )
            if booking:
                raise ValidationError(_(
                    "%(room)s xonasi bu vaqtda band qilingan: %(name)s (%(start)s - %(end)s).",
                    room=rec.room_id.name,
                    name=booking.name,
                    start=fields.Datetime.context_timestamp(rec, booking.start_datetime).strftime("%d.%m.%Y %H:%M"),
                    end=fields.Datetime.context_timestamp(rec, booking.end_datetime).strftime("%H:%M"),
                ))
