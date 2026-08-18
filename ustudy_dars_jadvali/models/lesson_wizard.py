from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


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


class DarsJadvaliAddLessonWizard(models.TransientModel):
    """Board cell click -> book a free room slot with an extra lesson.

    Creates a single edu.timetable entry (like adding an extra lesson by hand
    on the timetable), so the group's lesson numbering, davomat flow and the
    room-conflict guard all apply to it as usual. Room/date/time are prefilled
    from the clicked cell; teachers cannot use it (edu.timetable.create is
    admin-only via teacher_locked)."""
    _name = "dars.jadvali.add.lesson.wizard"
    _description = "Dars Jadvali: xonani band qilish (dars qo'shish)"

    purpose = fields.Selection(
        [
            ("dars", "Dars"),
            ("majlis", "Majlis"),
            ("konsultatsiya", "Konsultatsiya"),
            ("mehmon", "Mehmon uchun"),
        ],
        string="Maqsad",
        required=True,
        default="dars",
    )
    # Jadval doskasi opens the wizard with default_dars_only=True: there only
    # lessons may be added (non-dars bookings are made from Xonalar bandligi,
    # where the full purpose choice is offered).
    dars_only = fields.Boolean(string="Faqat dars")
    # required only for purpose == 'dars'; enforced in action_add_lesson (the
    # view mirrors it with a conditional required/invisible)
    group_id = fields.Many2one(
        "edu.group", string="Guruh",
        domain=[("active", "=", True)],
    )
    teacher_id = fields.Many2one("hr.employee", string="Ustoz")
    room_id = fields.Many2one(
        "edu.room", string="Xona", required=True,
        domain=[("active", "=", True)],
    )
    lesson_date = fields.Date(string="Sana", required=True)
    start_time = fields.Float(string="Boshlanish vaqti", required=True)
    end_time = fields.Float(string="Tugash vaqti", required=True)
    note = fields.Char(string="Izoh")
    # weekly recurring bookings ("har dushanba 12:00 da majlis") — non-dars only
    repeat_weekly = fields.Boolean(string="Har hafta takrorlash")
    repeat_until = fields.Date(string="Qachongacha")
    # single-day helper: the 3-day parity block the picked date belongs to
    # (Du/Chor/Jum or Se/Pay/Shan), the actual day highlighted green
    day_block_preview = fields.Html(
        string="Hafta kunlari", compute="_compute_day_block_preview",
        sanitize=False,  # server-generated markup only, no user input
    )

    @api.depends("lesson_date", "repeat_weekly")
    def _compute_day_block_preview(self):
        base = (
            "display:inline-block;min-width:56px;text-align:center;"
            "padding:5px 14px;margin-right:8px;border-radius:6px;"
            "font-weight:600;font-size:13px;"
        )
        active = base + "background:#28a745;color:#fff;"
        muted = base + "background:#e9ecef;color:#495057;"
        for rec in self:
            if not rec.lesson_date or rec.repeat_weekly:
                rec.day_block_preview = False
                continue
            wd = rec.lesson_date.weekday()
            if wd in (0, 2, 4):
                block = [(0, "Du"), (2, "Chor"), (4, "Jum")]
            elif wd in (1, 3, 5):
                block = [(1, "Se"), (3, "Pay"), (5, "Shan")]
            else:
                block = [(6, "Yak")]
            spans = "".join(
                '<span style="%s">%s</span>' % (active if d == wd else muted, label)
                for d, label in block
            )
            rec.day_block_preview = '<div style="padding-top:2px;">%s</div>' % spans

    @api.onchange("group_id")
    def _onchange_group_id(self):
        for rec in self:
            if not rec.group_id:
                continue
            rec.teacher_id = rec.group_id.teacher_id
            # keep the clicked slot as the start; the end follows the group's
            # configured lesson duration when it has one
            duration = (rec.group_id.lesson_end or 0.0) - (rec.group_id.lesson_start or 0.0)
            if duration > 0 and rec.start_time:
                rec.end_time = rec.start_time + duration

    def action_add_lesson(self):
        self.ensure_one()
        if self.dars_only and self.purpose != "dars":
            raise UserError(_("Jadval doskasidan faqat dars qo'shish mumkin. "
                              "Xona band qilish uchun Xonalar bandligi sahifasidan foydalaning."))
        if self.end_time <= self.start_time:
            raise UserError(_("Tugash vaqti boshlanish vaqtidan keyin bo'lishi kerak."))

        if self.purpose != "dars":
            return self._create_bookings()

        if not self.group_id:
            raise UserError(_("Dars qo'shish uchun guruhni tanlang."))

        return self._create_lesson()

    def _room_busy(self, start_dt, end_dt):
        """A short human description of what occupies the room in the slot,
        or False when it's free. Mirrors the two conflict constraints so the
        weekly-repeat path can SKIP busy dates instead of aborting them all."""
        booking = self.env["dars.jadvali.booking"].search([
            ("room_id", "=", self.room_id.id),
            ("start_datetime", "<", end_dt),
            ("end_datetime", ">", start_dt),
        ], limit=1)
        if booking:
            return booking.name
        lesson = self.env["edu.timetable"].search([
            ("room_id", "=", self.room_id.id),
            ("state", "!=", "cancelled"),
            ("group_id.active", "=", True),
            ("start_datetime", "<", end_dt),
            ("end_datetime", ">", start_dt),
        ], limit=1)
        if lesson:
            return lesson.group_id.name
        return False

    def _create_bookings(self):
        """Create the non-dars booking(s): one date, or every week up to
        repeat_until. Busy dates are skipped and reported, not fatal.
        _make_utc_datetime only uses the user's TZ, so calling it on the
        empty edu.group recordset is fine."""
        Group = self.env["edu.group"]
        Booking = self.env["dars.jadvali.booking"]

        dates = [self.lesson_date]
        if self.repeat_weekly:
            if not self.repeat_until or self.repeat_until < self.lesson_date:
                raise UserError(_(
                    "Har hafta takrorlash uchun \"Qachongacha\" sanasini "
                    "kiriting (boshlanish sanasidan keyin)."))
            d = self.lesson_date + timedelta(days=7)
            while d <= self.repeat_until and len(dates) < 53:  # max 1 year
                dates.append(d)
                d += timedelta(days=7)

        created, busy = 0, []
        for d in dates:
            start_dt = Group._make_utc_datetime(d, self.start_time)
            end_dt = Group._make_utc_datetime(d, self.end_time)
            clash = self._room_busy(start_dt, end_dt)
            if clash:
                busy.append("%s — %s" % (d.strftime("%d.%m.%Y"), clash))
                continue
            Booking.create({
                "purpose": self.purpose,
                "room_id": self.room_id.id,
                "start_datetime": start_dt,
                "end_datetime": end_dt,
                "note": self.note,
            })
            created += 1

        if not created:
            raise UserError(_(
                "Band yaratilmadi — tanlangan vaqt allaqachon band:\n%s"
            ) % "\n".join(busy))

        message = _("%s ta xona bandi yaratildi.") % created
        if busy:
            message += _("\nO'tkazib yuborildi (band): %s") % "; ".join(busy)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": message,
                "type": "warning" if busy else "success",
                "sticky": bool(busy),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _create_lesson(self):
        weekday = self.env["edu.weekday"].search(
            [("sequence", "=", self.lesson_date.weekday() + 1)], limit=1
        )
        if not weekday:
            raise UserError(_("Hafta kuni topilmadi (edu.weekday, sequence=%s).")
                            % (self.lesson_date.weekday() + 1))

        group = self.group_id
        start_dt = group._make_utc_datetime(self.lesson_date, self.start_time)
        end_dt = group._make_utc_datetime(self.lesson_date, self.end_time)

        # friendly guard before the partial unique index on
        # (group_id, start_datetime) turns this into a raw SQL error
        duplicate = self.env["edu.timetable"].search([
            ("group_id", "=", group.id),
            ("start_datetime", "=", start_dt),
            ("state", "!=", "cancelled"),
        ], limit=1)
        if duplicate:
            raise UserError(_(
                "%s guruhida bu vaqtda allaqachon dars bor: %s."
            ) % (group.name, duplicate.name))

        # the room-conflict constraint on edu.timetable fires on create and
        # reports the overlapping group/time itself
        self.env["edu.timetable"].create({
            "group_id": group.id,
            "teacher_id": self.teacher_id.id or group.teacher_id.id,
            "room_id": self.room_id.id,
            "weekday_id": weekday.id,
            "start_datetime": start_dt,
            "end_datetime": end_dt,
            "state": "scheduled",
        })
        return {"type": "ir.actions.act_window_close"}
