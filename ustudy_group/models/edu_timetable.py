from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta, time
import pytz


class EduTimetable(models.Model):
    _name = "edu.timetable"
    _description = "Education Timetable"
    _order = "start_datetime"

    name = fields.Char(string="Lesson Title", compute="_compute_name", store=True)

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        related="group_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )

    group_id = fields.Many2one(
        "edu.group",
        string="Group",
        required=True,
        ondelete="cascade",
        index=True,
    )
    group_active = fields.Boolean(
        string="Group Active",
        related="group_id.active",
        store=True,
        index=True,
    )

    course_id = fields.Many2one(
        "edu.course",
        string="Course",
        related="group_id.course_id",
        store=True,
    )

    teacher_id = fields.Many2one(
        "hr.employee",
        string="Teacher",
        index=True,
    )

    @api.onchange("group_id")
    def _onchange_group_teacher(self):
        for rec in self:
            if rec.group_id and not rec.teacher_id:
                rec.teacher_id = rec.group_id.teacher_id

    is_today = fields.Boolean(
        string="Is Today",
        compute="_compute_is_today",
        store=False,
    )

    weekday_id = fields.Many2one(
        "edu.weekday",
        string="Weekday",
        required=True,
        index=True,
    )

    room_id = fields.Many2one(
        "edu.room",
        string="Room",
        required=True,
        ondelete="restrict",
        domain="[('company_id', '=', company_id)]",
        index=True,
    )

    slide_id = fields.Many2one(
        "slide.slide",
        string="Lesson/Slide",
        domain="[('channel_id', '=', slide_channel_id)]",
    )

    slide_channel_id = fields.Many2one(
        "slide.channel",
        string="Course Channel",
        related="group_id.course_id.slide_channel_id",
        store=True,
    )

    start_datetime = fields.Datetime(string="Start Time", required=True, index=True)
    end_datetime = fields.Datetime(string="End Time", required=True)

    start_date = fields.Date(string="Start Date", compute="_compute_dates", store=True, index=True)
    end_date = fields.Date(string="End Date", compute="_compute_dates", store=True, index=True)

    duration = fields.Float(string="Duration (hours)", compute="_compute_duration", store=True)

    state = fields.Selection(
        [
            ("scheduled", "Scheduled"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="scheduled",
        tracking=True,
    )

    notes = fields.Text(string="Notes")

    color = fields.Integer(string="Color", related="group_id.group_color", store=False)
    student_count = fields.Integer(string="Students", related="group_id.student_count", store=False)

    lesson_sequence = fields.Integer(
        string="No.",
        compute="_compute_lesson_sequence",
        store=False,
    )

    # -----------------------------
    # Optional Homework integration
    # -----------------------------
    has_homework = fields.Boolean(
        string="Has Homework",
        compute="_compute_has_homework",
        store=True,  # ✅ so you can filter/search in list view
        index=True,
    )

    submission_ratio = fields.Char(string="Submissions", compute="_compute_submission_ratio", store=False)
    submitted_count = fields.Integer(string="Submitted", compute="_compute_submission_ratio", store=False)
    group_student_count = fields.Integer(string="Students", compute="_compute_submission_ratio", store=False)

    # ---------- helpers ----------
    def _model_exists(self, model_name: str) -> bool:
        # ✅ safe even if module not installed
        return model_name in self.env

    def _group_student_partner_ids(self):
        self.ensure_one()
        return self.group_id.student_line_ids.mapped("student_id").ids

    # ---------- computes ----------
    @api.depends("start_datetime", "end_datetime")
    def _compute_dates(self):
        for rec in self:
            rec.start_date = rec.start_datetime.date() if rec.start_datetime else False
            rec.end_date = rec.end_datetime.date() if rec.end_datetime else False

    @api.depends("start_date")
    def _compute_is_today(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_today = rec.start_date == today

    @api.depends("group_id.name", "weekday_id.name", "start_datetime")
    def _compute_name(self):
        for record in self:
            if record.group_id and record.weekday_id and record.start_datetime:
                start_time = fields.Datetime.context_timestamp(record, record.start_datetime).strftime("%H:%M")
                record.name = f"{record.group_id.name} - {record.weekday_id.name} {start_time}"
            else:
                record.name = "New Timetable Entry"

    @api.depends("start_datetime", "end_datetime")
    def _compute_duration(self):
        for record in self:
            if record.start_datetime and record.end_datetime:
                delta = record.end_datetime - record.start_datetime
                record.duration = delta.total_seconds() / 3600.0
            else:
                record.duration = 0.0

    @api.depends("group_id", "group_id.start_lesson_number", "start_datetime")
    def _compute_lesson_sequence(self):
        group_ids = list({rec.group_id.id for rec in self if rec.group_id})
        seq_map = {}
        for gid in group_ids:
            group = self.env["edu.group"].browse(gid)
            start = max(group.start_lesson_number or 1, 1)
            ordered = self.env["edu.timetable"].search(
                [("group_id", "=", gid)],
                order="start_datetime asc",
            )
            for i, r in enumerate(ordered, start):
                seq_map[r.id] = i
        for rec in self:
            rec.lesson_sequence = seq_map.get(rec.id, 0)

    @api.depends("slide_id")
    def _compute_has_homework(self):
        # ✅ Works even if edu.homework is NOT installed
        for rec in self:
            rec.has_homework = False
            if not rec.slide_id:
                continue
            if not rec._model_exists("edu.homework"):
                continue

            Homework = rec.env["edu.homework"]
            rec.has_homework = bool(
                Homework.search_count(
                    [
                        ("slide_id", "=", rec.slide_id.id),
                        ("is_published", "=", True),
                    ]
                )
            )

    @api.depends("group_id", "slide_id")
    def _compute_submission_ratio(self):
        for rec in self:
            total = rec.group_id.student_count or 0
            rec.group_student_count = total
            rec.submitted_count = 0
            rec.submission_ratio = f"0/{total}" if total else "0/0"

            if total == 0 or not rec.slide_id:
                continue

            # ✅ If homework models are not installed -> keep default 0/x
            if not rec._model_exists("edu.homework") or not rec._model_exists("edu.homework.submission"):
                continue

            Homework = rec.env["edu.homework"]
            Submission = rec.env["edu.homework.submission"]

            hw = Homework.search(
                [
                    ("slide_id", "=", rec.slide_id.id),
                    ("is_published", "=", True),
                ],
                limit=1,
            )
            if not hw:
                continue

            student_ids = rec._group_student_partner_ids()
            submitted = Submission.search_count(
                [
                    ("homework_id", "=", hw.id),
                    ("student_id", "in", student_ids),
                ]
            )
            rec.submitted_count = submitted
            rec.submission_ratio = f"{submitted}/{total}"

    # ---------- constraints ----------
    @api.constrains("start_datetime", "end_datetime")
    def _check_dates(self):
        for record in self:
            if record.start_datetime and record.end_datetime and record.end_datetime <= record.start_datetime:
                raise ValidationError(_("End time must be after start time."))

    @api.constrains("room_id", "start_datetime", "end_datetime")
    def _check_room_availability(self):
        for record in self:
            if not (record.room_id and record.start_datetime and record.end_datetime):
                continue

            domain = [
                ("id", "!=", record.id),
                ("room_id", "=", record.room_id.id),
                ("state", "!=", "cancelled"),
                ("start_datetime", "<", record.end_datetime),
                ("end_datetime", ">", record.start_datetime),
            ]

            conflicts = self.search(domain, limit=1)
            if conflicts:
                raise ValidationError(
                    _(
                        "Room %(room)s is already booked from %(start)s to %(end)s for %(group)s",
                        room=record.room_id.name,
                        start=conflicts.start_datetime,
                        end=conflicts.end_datetime,
                        group=conflicts.group_id.name,
                    )
                )

    # ---------- actions ----------
    def action_mark_completed(self):
        self.write({"state": "completed"})

    def action_mark_in_progress(self):
        if not self.slide_id:
            raise UserError(_("Darsni boshlash uchun dars mavzusini belgilang"))
        
        self.write({"state": "in_progress"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_view_group_homework_submissions(self):
        """Open submissions from timetable (only if homework module exists)."""
        self.ensure_one()

        if not self._model_exists("edu.homework") or not self._model_exists("edu.homework.submission"):
            return False
        if not self.slide_id:
            return False

        Homework = self.env["edu.homework"]
        hw = Homework.search(
            [
                ("slide_id", "=", self.slide_id.id),
                ("is_published", "=", True),
            ],
            limit=1,
        )
        if not hw:
            return False

        student_ids = self._group_student_partner_ids()
        return {
            "name": _("Submissions"),
            "type": "ir.actions.act_window",
            "res_model": "edu.homework.submission",
            "view_mode": "list,form",
            "domain": [
                ("homework_id", "=", hw.id),
                ("student_id", "in", student_ids),
            ],
        }


class EduGroup(models.Model):
    _inherit = "edu.group"

    # --- lesson count mode ---
    lesson_count = fields.Integer(string="Lesson Count", default=0, tracking=True)
    use_lesson_count = fields.Boolean(string="Use lesson count", default=True, tracking=True)

    timetable_ids = fields.One2many("edu.timetable", "group_id", string="Timetable Entries")
    timetable_count = fields.Integer(string="Timetable Entries", compute="_compute_timetable_count", store=False)

    lesson_start_time = fields.Float(
        string="Lesson Start Time",
        default=9.0,
        help="Default start time for lessons (e.g., 9.0 = 9:00 AM)",
    )
    lesson_duration = fields.Float(
        string="Lesson Duration (hours)",
        default=1.5,
        help="Duration of each lesson in hours",
    )

    @api.depends("timetable_ids")
    def _compute_timetable_count(self):
        for group in self:
            group.timetable_count = len(group.timetable_ids)

    # ---------- helpers ----------
    def _float_to_hour_minute(self, float_time):
        total_minutes = int(round(float_time * 60))
        hour = total_minutes // 60
        minute = total_minutes % 60
        return hour, minute

    def _make_utc_datetime(self, date_value, float_time):
        """Create UTC naive datetime from a date + float time using user's TZ."""
        user_tz = pytz.timezone(self.env.user.tz or "UTC")
        hour, minute = self._float_to_hour_minute(float_time)
        local_dt = datetime.combine(date_value, time(hour=hour, minute=minute))
        local_dt = user_tz.localize(local_dt)
        return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)

    def _compute_end_date_from_count(self):
        """Return date of Nth lesson based on start_date + lesson_days + lesson_count."""
        self.ensure_one()
        if not self.start_date or not self.lesson_days or not self.lesson_count:
            return False

        allowed = set(self.lesson_days.mapped("sequence"))  # 1..7 (Mon..Sun)
        d = self.start_date
        lessons = 0

        while lessons < self.lesson_count:
            if (d.weekday() + 1) in allowed:
                lessons += 1
                if lessons == self.lesson_count:
                    return d
            d += timedelta(days=1)

        return False

    def _ensure_end_date(self):
        """Ensure end_date is filled (server-side), for button actions."""
        self.ensure_one()
        if self.end_date:
            return

        if self.use_lesson_count and self.lesson_count:
            end_date = self._compute_end_date_from_count()
            if end_date:
                self.end_date = end_date

    @api.onchange("start_date", "lesson_days", "lesson_count", "use_lesson_count")
    def _onchange_end_date_from_count(self):
        for rec in self:
            if not rec.use_lesson_count:
                continue
            if not rec.start_date or not rec.lesson_days or not rec.lesson_count:
                continue

            allowed = set(rec.lesson_days.mapped("sequence"))
            d = rec.start_date
            lessons = 0
            while lessons < rec.lesson_count:
                if (d.weekday() + 1) in allowed:
                    lessons += 1
                    if lessons == rec.lesson_count:
                        rec.end_date = d
                        break
                d += timedelta(days=1)

    # ---------- actions ----------
    def action_view_timetable(self):
        self.ensure_one()
        return {
            "name": _("Timetable - %s", self.name),
            "type": "ir.actions.act_window",
            "res_model": "edu.timetable",
            "view_mode": "calendar,list,form",
            "domain": [("group_id", "=", self.id)],
            "context": {
                "default_group_id": self.id,
                "default_room_id": self.lesson_room.id if self.lesson_room else False,
                "search_default_scheduled_from_today": 1,
            },
        }

    def action_generate_or_regenerate_timetable(self):
        self.ensure_one()
        Timetable = self.env["edu.timetable"]
        existing = Timetable.search_count([("group_id", "=", self.id), ("state", "!=", "cancelled")])
        return self.action_regenerate_timetable() if existing else self.action_generate_timetable()

    def _get_channel_lessons(self):
        """✅ IMPORTANT FIX: don't filter by slide_category == 'lesson' (often not present)."""
        self.ensure_one()
        if not self.course_id or not self.course_id.slide_channel_id:
            return self.env["slide.slide"]
        # keep a stable order
        return self.course_id.slide_channel_id.slide_ids.sorted(lambda s: (s.sequence or 0, s.id))

    # ------------------------------------------------------------------
    # Floating-schedule helpers
    # ------------------------------------------------------------------
    def _get_weekly_slots(self):
        """Return the recurring weekly slots used to build the timetable.

        Each slot is a dict: ``weekday_id``, ``weekday_seq``, ``time_from``,
        ``time_to``, ``room_id``, ``teacher_id``.

        Source of truth = the floating ``schedule_ids`` lines (so a group can
        meet at different times on different days). If a group has no schedule
        lines yet, we fall back to the legacy single-time fields
        (``lesson_days`` + ``lesson_start``/``lesson_end``) so existing groups
        keep working unchanged.
        """
        self.ensure_one()
        slots = []
        active_lines = self.schedule_ids.filtered(lambda s: s.active)
        if active_lines:
            for line in active_lines:
                room = line.room_id or self.lesson_room
                teacher = line.teacher_id or self.teacher_id
                slots.append({
                    "weekday_id": line.weekday_id.id,
                    "weekday_seq": line.weekday_id.sequence,
                    "time_from": line.time_from,
                    "time_to": line.time_to,
                    "room_id": room.id if room else False,
                    "teacher_id": teacher.id if teacher else False,
                })
        else:
            for weekday in self.lesson_days:
                slots.append({
                    "weekday_id": weekday.id,
                    "weekday_seq": weekday.sequence,
                    "time_from": self.lesson_start,
                    "time_to": self.lesson_end,
                    "room_id": self.lesson_room.id if self.lesson_room else False,
                    "teacher_id": self.teacher_id.id if self.teacher_id else False,
                })
        return slots

    def _validate_schedule_for_generation(self):
        """Operational pre-checks for timetable generation.

        These are generator-input guards (not the capacity rule), so a guiding
        UserError is appropriate here.
        """
        self.ensure_one()
        slots = self._get_weekly_slots()
        if not slots:
            raise UserError(_(
                "Add at least one weekly schedule slot (or legacy lesson days) "
                "before generating the timetable."
            ))
        if not self.start_date or not self.end_date:
            raise UserError(_("Please set start and end dates before generating timetable."))
        if self.start_date >= self.end_date:
            raise UserError(_("End date must be after start date."))
        for slot in slots:
            if not slot["room_id"]:
                raise UserError(_(
                    "Every schedule slot needs a room. Set a room on the slot "
                    "or a default 'Lesson Room' on the group."
                ))
            if not slot["time_from"] or not slot["time_to"] or slot["time_from"] >= slot["time_to"]:
                raise UserError(_(
                    "Every schedule slot needs a valid start/end time "
                    "(end must be after start)."
                ))
        return slots

    def _iter_lesson_dates(self, start_from):
        """Yield ``(date, slot)`` for each lesson between ``start_from`` and
        ``end_date``, honoring ``lesson_count`` when ``use_lesson_count`` is on.

        Multiple slots can share the same weekday; within a day they are
        ordered by start time so slide numbering stays chronological.
        """
        self.ensure_one()
        slots_by_day = {}
        for slot in self._get_weekly_slots():
            slots_by_day.setdefault(slot["weekday_seq"], []).append(slot)
        for seq in slots_by_day:
            slots_by_day[seq].sort(key=lambda s: s["time_from"])

        remaining = self.lesson_count if (self.use_lesson_count and self.lesson_count) else None
        current_date = start_from
        while current_date <= self.end_date and (remaining is None or remaining > 0):
            weekday_seq = current_date.weekday() + 1
            for slot in slots_by_day.get(weekday_seq, []):
                if remaining is not None and remaining <= 0:
                    break
                yield current_date, slot
                if remaining is not None:
                    remaining -= 1
            current_date += timedelta(days=1)

    def _build_timetable_entry(self, lesson_date, slot, slide_id):
        """Build a single ``(0, 0, vals)`` command for a timetable entry."""
        self.ensure_one()
        return (0, 0, {
            "group_id": self.id,
            "weekday_id": slot["weekday_id"],
            "room_id": slot["room_id"],
            "start_datetime": self._make_utc_datetime(lesson_date, slot["time_from"]),
            "end_datetime": self._make_utc_datetime(lesson_date, slot["time_to"]),
            "slide_id": slide_id,
            "state": "scheduled",
            "teacher_id": slot["teacher_id"],
        })

    def action_regenerate_timetable(self):
        self.ensure_one()
        self._ensure_end_date()
        self._validate_schedule_for_generation()

        today = fields.Date.context_today(self)
        regen_from_date = max(today, self.start_date)
        if regen_from_date > self.end_date:
            raise UserError(_("Nothing to regenerate: today is after the end date."))

        regen_from_dt_utc = self._make_utc_datetime(regen_from_date, 0.0)
        Timetable = self.env["edu.timetable"]

        # Drop only future (non-cancelled) entries; keep history intact.
        future_entries = Timetable.search([
            ("group_id", "=", self.id),
            ("start_datetime", ">=", regen_from_dt_utc),
            ("state", "!=", "cancelled"),
        ])
        if future_entries:
            future_entries.unlink()

        lessons = self._get_channel_lessons()

        # Resume slide numbering after the slides already used in the past.
        past_entries = Timetable.search([
            ("group_id", "=", self.id),
            ("start_datetime", "<", regen_from_dt_utc),
            ("state", "!=", "cancelled"),
        ], order="start_datetime asc")
        slide_start = max((self.start_lesson_number or 1) - 1, 0)
        lesson_index = slide_start + len(past_entries.filtered(lambda r: r.slide_id))

        entries = []
        for lesson_date, slot in self._iter_lesson_dates(regen_from_date):
            slide_id = False
            if lessons and lesson_index < len(lessons):
                slide_id = lessons[lesson_index].id
                lesson_index += 1
            entries.append(self._build_timetable_entry(lesson_date, slot, slide_id))

        if entries:
            self.write({"timetable_ids": entries})
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "message": _("%s timetable entries regenerated (from %s)!", len(entries), regen_from_date),
                    "type": "success",
                    "sticky": False,
                },
            }

        raise UserError(_("No timetable entries were generated. Please check your settings."))

    def action_generate_timetable(self):
        self.ensure_one()
        self._ensure_end_date()
        self._validate_schedule_for_generation()

        lessons = self._get_channel_lessons()

        existing_entries = self.env["edu.timetable"].search([("group_id", "=", self.id)])
        if existing_entries:
            existing_entries.unlink()

        lesson_index = max((self.start_lesson_number or 1) - 1, 0)
        entries = []
        for lesson_date, slot in self._iter_lesson_dates(self.start_date):
            slide_id = False
            if lessons and lesson_index < len(lessons):
                slide_id = lessons[lesson_index].id
                lesson_index += 1
            entries.append(self._build_timetable_entry(lesson_date, slot, slide_id))

        if entries:
            self.write({"timetable_ids": entries})
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "message": _("%s timetable entries generated successfully!", len(entries)),
                    "type": "success",
                    "sticky": False,
                },
            }

        raise UserError(_("No timetable entries were generated. Please check your settings."))
