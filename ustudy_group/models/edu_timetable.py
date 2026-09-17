from odoo import api, fields, models, tools, _
from odoo.exceptions import AccessError, UserError, ValidationError
from datetime import datetime, timedelta, time
import pytz

from .edu_group import CLOSED_GROUP_STATES, teacher_locked


class EduTimetable(models.Model):
    _name = "edu.timetable"
    _description = "Education Timetable"
    _order = "start_datetime"

    def init(self):
        # Prevent duplicate lessons: a group can have at most one non-cancelled
        # timetable per start time. Partial (excludes cancelled) so a cancelled
        # lesson can coexist with its rescheduled replacement at the same slot.
        # A plain _sql_constraints unique can't express the WHERE clause.
        tools.create_index(
            self.env.cr,
            "edu_timetable_group_start_active_uniq",
            self._table,
            ["group_id", "start_datetime"],
            unique=True,
            where="state <> 'cancelled'",
        )

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
        domain="[('channel_id', '=', slide_channel_id), ('is_category', '=', False)]",
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

    # Set by edu.group's "course finished" hook on the lessons it cancels, so
    # reopening the group ("Faol" again) can put exactly those lessons back —
    # a manually cancelled lesson (holiday, moved day) must stay cancelled.
    auto_cancelled_on_done = fields.Boolean(
        string="Auto-cancelled (course finished)",
        default=False,
        copy=False,
        index=True,
    )

    color = fields.Integer(string="Color", related="group_id.group_color", store=False)
    student_count = fields.Integer(string="Students", related="group_id.student_count", store=False)

    lesson_sequence = fields.Integer(
        string="No.",
        compute="_compute_lesson_sequence",
        store=False,
    )

    module_id = fields.Many2one(
        "edu.module",
        string="Modul",
        compute="_compute_module_id",
        store=False,
        help="Module this lesson belongs to, derived from its lesson number "
             "(lesson_sequence) and lessons_per_module in the config.",
    )

    # UI flag: True when the current user is a locked teacher — schedule
    # fields render readonly in the views. Enforcement is in write()/create().
    teacher_readonly = fields.Boolean(compute="_compute_teacher_readonly")

    def _compute_teacher_readonly(self):
        locked = teacher_locked(self.env)
        for rec in self:
            rec.teacher_readonly = locked

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

    # Stored name must not depend on who triggers the recompute:
    # context_timestamp falls back to UTC when the acting user has no tz
    # (cron, server-side recomputes), which stored e.g. "11:30" for a
    # 16:30 Tashkent lesson. Pin the school's timezone instead.
    NAME_TZ = pytz.timezone("Asia/Tashkent")

    @api.depends("group_id.name", "weekday_id.name", "start_datetime")
    def _compute_name(self):
        for record in self:
            if record.group_id and record.weekday_id and record.start_datetime:
                local_dt = pytz.utc.localize(record.start_datetime).astimezone(self.NAME_TZ)
                record.name = f"{record.group_id.name} - {record.weekday_id.name} {local_dt.strftime('%H:%M')}"
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
                [("group_id", "=", gid), ("state", "!=", "cancelled")],
                order="start_datetime asc",
            )
            for i, r in enumerate(ordered, start):
                seq_map[r.id] = i
        for rec in self:
            rec.lesson_sequence = seq_map.get(rec.id, 0)

    @api.depends("lesson_sequence")
    def _compute_module_id(self):
        for rec in self:
            if rec.group_id and rec.lesson_sequence:
                module, _pos = rec.group_id._module_position_for_lesson(rec.lesson_sequence)
                rec.module_id = module
            else:
                rec.module_id = False

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
            domain = [
                ("slide_id", "=", rec.slide_id.id),
                ("is_published", "=", True),
            ]
            # Group lesson tasks (ustudy_homework) only count for their own
            # group — another group's task must not flag this lesson.
            if "group_id" in Homework._fields:
                domain += [
                    "|",
                    ("group_id", "=", False),
                    ("group_id", "=", rec.group_id.id),
                ]
            rec.has_homework = bool(Homework.search_count(domain))

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
                # Archived groups' lessons don't hold the room (the timetable
                # board hides them too, so a conflict would be invisible).
                # Checked via group_id, not the stored group_active copy: a
                # NULL in the copy would silently drop a live lesson here.
                ("group_id.active", "=", True),
                # Same reasoning for finished/cancelled groups: they are off
                # the schedule, so their leftover lessons must not block a
                # room for a group that is still running.
                ("group_id.state", "not in", list(CLOSED_GROUP_STATES)),
                ("start_datetime", "<", record.end_datetime),
                ("end_datetime", ">", record.start_datetime),
            ]

            conflicts = self.search(domain, limit=1)
            if conflicts:
                start_local = fields.Datetime.context_timestamp(record, conflicts.start_datetime)
                end_local = fields.Datetime.context_timestamp(record, conflicts.end_datetime)
                raise ValidationError(
                    _(
                        "Room %(room)s is already booked from %(start)s to %(end)s for %(group)s",
                        room=record.room_id.name,
                        start=start_local.strftime("%d.%m.%Y %H:%M"),
                        end=end_local.strftime("%d.%m.%Y %H:%M"),
                        group=conflicts.group_id.name,
                    )
                )

    def _room_taken_by_other_group(self):
        """True when another live lesson/booking already occupies this room in
        this slot. Same rule as _check_room_availability, but as a question
        instead of a ValidationError (used when reopening a group restores its
        lessons — see edu.group._restore_auto_cancelled_lessons)."""
        self.ensure_one()
        if not (self.room_id and self.start_datetime and self.end_datetime):
            return False
        return bool(self.search_count([
            ("id", "!=", self.id),
            ("room_id", "=", self.room_id.id),
            ("state", "!=", "cancelled"),
            ("group_id.active", "=", True),
            ("group_id.state", "not in", list(CLOSED_GROUP_STATES)),
            ("start_datetime", "<", self.end_datetime),
            ("end_datetime", ">", self.start_datetime),
        ]))

    # ---------- teacher lock ----------
    # Teachers run lessons (state transitions of the attendance flow, topic,
    # notes) but never reschedule: time/day/room/assignment changes, creating
    # and deleting lessons are administration work.
    TEACHER_PROTECTED_FIELDS = {
        "group_id", "teacher_id", "weekday_id", "room_id",
        "start_datetime", "end_datetime",
    }

    # ---------- finished groups stay off the schedule ----------
    def _check_group_open(self, group):
        """A group whose course is over (Tugallandi/Bekor qilindi) is off the
        schedule: marking it done cancels its remaining lessons, so letting a
        new one be added right after would silently put it back on the
        timetable and the Jadval doskasi board. Guarded here (not only in the
        wizard domain) because every add path — wizard, import, list view,
        regenerate — goes through create/write."""
        if not group or group.state not in CLOSED_GROUP_STATES:
            return
        if self.env.context.get("skip_closed_group_check"):
            return
        raise UserError(_(
            "%(group)s guruhi \"%(state)s\" holatida — tugagan guruhga yangi dars "
            "qo'shib bo'lmaydi. Avval guruhni qayta ishga tushiring "
            "(\"Qayta boshlash\"), keyin darsni qo'shing.",
            group=group.display_name,
            state=dict(group._fields["state"]._description_selection(self.env))
                .get(group.state, group.state),
        ))

    @api.model_create_multi
    def create(self, vals_list):
        if teacher_locked(self.env):
            raise AccessError(_("O'qituvchi dars jadvaliga yangi dars qo'sha olmaydi. Bu administratsiya vazifasi."))
        Group = self.env["edu.group"]
        for vals in vals_list:
            if vals.get("state") == "cancelled":
                continue  # a cancelled entry is not on the schedule
            self._check_group_open(Group.browse(vals.get("group_id")).exists())
        return super().create(vals_list)

    def write(self, vals):
        # Moving a lesson onto a finished group, or reviving a cancelled one of
        # a finished group, puts it back on the board just like creating it.
        if "group_id" in vals or vals.get("state") in ("scheduled", "in_progress"):
            target = (
                self.env["edu.group"].browse(vals["group_id"]).exists()
                if vals.get("group_id")
                else None
            )
            for rec in self:
                self._check_group_open(target or rec.group_id)
        if teacher_locked(self.env):
            blocked = self.TEACHER_PROTECTED_FIELDS & set(vals)
            if blocked:
                raise AccessError(_(
                    "O'qituvchi dars vaqti, kuni, xonasi yoki guruhini o'zgartira olmaydi (%s). Bu administratsiya vazifasi.",
                    ", ".join(sorted(blocked)),
                ))
            if vals.get("state") == "cancelled":
                raise AccessError(_("O'qituvchi darsni bekor qila olmaydi. Bu administratsiya vazifasi."))
        return super().write(vals)

    def unlink(self):
        if teacher_locked(self.env):
            raise AccessError(_("O'qituvchi darsni o'chira olmaydi. Bu administratsiya vazifasi."))
        return super().unlink()

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

    def _planned_lesson_total(self):
        """How many timetable entries this group should hold.

        lesson_count ("Jami darslar soni") is the course's TOTAL lesson
        number, not the number of entries to create: a group starting at
        lesson 109 of a 144-lesson course holds 36 entries (No. 109..144).
        Returns None when lesson-count mode is off."""
        self.ensure_one()
        if not (self.use_lesson_count and self.lesson_count):
            return None
        start_no = max(self.start_lesson_number or 1, 1)
        return self.lesson_count - start_no + 1

    def _compute_end_date_from_count(self):
        """Return the date of the group's LAST lesson based on start_date +
        lesson_days + planned lesson total (see _planned_lesson_total)."""
        self.ensure_one()
        total = self._planned_lesson_total()
        if not self.start_date or not self.lesson_days or not total or total <= 0:
            return False

        allowed = set(self.lesson_days.mapped("sequence"))  # 1..7 (Mon..Sun)
        d = self.start_date
        lessons = 0

        while lessons < total:
            if (d.weekday() + 1) in allowed:
                lessons += 1
                if lessons == total:
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

    @api.onchange("start_date", "lesson_days", "lesson_count", "use_lesson_count",
                  "start_lesson_number")
    def _onchange_end_date_from_count(self):
        for rec in self:
            if not rec.use_lesson_count:
                continue
            if not rec.start_date or not rec.lesson_days or not rec.lesson_count:
                continue
            total = rec._planned_lesson_total()
            if not total or total <= 0:
                continue

            allowed = set(rec.lesson_days.mapped("sequence"))
            d = rec.start_date
            lessons = 0
            while lessons < total:
                if (d.weekday() + 1) in allowed:
                    lessons += 1
                    if lessons == total:
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

    def _get_lessons_by_no(self):
        """Map {lesson_no: slide} for the course's lessons (non-category slides
        that carry a lesson number). The timetable attaches a slide to a day by
        matching the day's 'No.' against this lesson number."""
        self.ensure_one()
        if not self.course_id or not self.course_id.slide_channel_id:
            return {}
        lessons = self.course_id.slide_channel_id.slide_ids.filtered(
            lambda s: not s.is_category and s.lesson_no
        )
        return {s.lesson_no: s for s in lessons}

    def action_regenerate_timetable(self):
        self.ensure_one()
        self._ensure_end_date()

        if not self.lesson_days:
            raise UserError(_("Please select lesson days before generating timetable."))
        if not self.lesson_room:
            raise UserError(_("Please select a lesson room before generating timetable."))
        if not self.start_date or not self.end_date:
            raise UserError(_("Please set start and end dates before generating timetable."))
        if self.start_date > self.end_date:
            raise UserError(_("End date must not be before start date."))
        if not self.lesson_start or not self.lesson_end:
            raise UserError(_("Please set lesson start and end times."))
        if self.lesson_start >= self.lesson_end:
            raise UserError(_("Lesson end time must be after start time."))

        if not self.lesson_room.active:
            raise UserError(_(
                "%s xonasi arxivlangan — jadval unda ko'rinmaydi. Avval "
                "guruhga faol xonani tanlang.", self.lesson_room.name))

        today = fields.Date.context_today(self)
        regen_from_date = max(today, self.start_date)

        # Data guard BEFORE any destructive step: a start lesson beyond the
        # course total means "Jami darslar soni" holds stale/old-style data —
        # wiping the schedule from it would destroy valid lessons.
        planned_total = self._planned_lesson_total()
        # In lesson-count mode the PLAN drives regeneration, so an end date in
        # the past just means the schedule must be extended; without a plan the
        # end date is the only boundary and being past it is a real error.
        if planned_total is None and regen_from_date > self.end_date:
            raise UserError(_("Nothing to regenerate: today is after the end date."))
        if planned_total is not None and planned_total <= 0:
            raise UserError(_(
                "Jami darslar soni (%s) boshlangan darsdan (%s) kichik. Avval "
                "\"Jami darslar soni\" maydonini kursning umumiy darslar soniga "
                "to'g'rilang, keyin jadvalni qayta yarating.",
                self.lesson_count, self.start_lesson_number))

        regen_from_dt_utc = self._make_utc_datetime(regen_from_date, 0.0)

        Timetable = self.env["edu.timetable"]

        # Only wipe lessons that haven't been held yet. Started lessons
        # (in_progress/completed) carry attendance records with
        # ondelete=cascade — deleting them would silently destroy the
        # attendance history, so they must survive regeneration.
        Timetable.search(
            [
                ("group_id", "=", self.id),
                ("start_datetime", ">=", regen_from_dt_utc),
                ("state", "=", "scheduled"),
            ]
        ).unlink()

        lessons_by_no = self._get_lessons_by_no()

        past_entries = Timetable.search(
            [
                ("group_id", "=", self.id),
                ("start_datetime", "<", regen_from_dt_utc),
                ("state", "!=", "cancelled"),
            ]
        )
        # Started lessons on/after the regeneration day survived the wipe:
        # their dates must not receive a second entry (partial unique index on
        # group_id/start_datetime) and they still occupy a "No." slot.
        kept_entries = Timetable.search(
            [
                ("group_id", "=", self.id),
                ("start_datetime", ">=", regen_from_dt_utc),
                ("state", "not in", ("scheduled", "cancelled")),
            ]
        )
        kept_dates = {
            fields.Datetime.context_timestamp(self, e.start_datetime).date()
            for e in kept_entries
        }

        # The timetable "No." numbers every non-cancelled entry sequentially from
        # start_lesson_number, so the first regenerated day continues right after
        # the kept past entries. We attach the slide whose lesson_no == that "No.".
        next_lesson_no = max(self.start_lesson_number or 1, 1) + len(past_entries)

        timetable_entries = []
        current_date = regen_from_date
        # Lessons already held before the regeneration day count toward the
        # planned total (which respects the start offset — see
        # _planned_lesson_total).
        remaining = None
        if planned_total is not None:
            # Only past entries are subtracted here: kept (started) entries on
            # or after the regeneration day are decremented inside the loop
            # when their date is reached — subtracting them here too would
            # double-count them.
            remaining = planned_total - len(past_entries)
            if remaining <= 0:
                # The group already holds its full plan (or more): the wipe
                # above removed the excess scheduled lessons — that IS the fix
                # for over-generated schedules, so report it instead of the
                # generic "nothing generated" error.
                self._sync_end_date_to_schedule()
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "message": _(
                            "Reja bo'yicha darslar soni to'lgan (%s ta). Bugundan "
                            "keyingi ortiqcha rejalashtirilgan darslar o'chirildi.",
                            planned_total),
                        "type": "success",
                        "sticky": False,
                    },
                }

        # In lesson-count mode the loop runs until the plan is full — a stale
        # end_date must NOT cut the schedule short (a group whose lesson days
        # were reduced after the end date was computed would otherwise lose
        # its last lessons forever: regenerate could never add them back).
        # The hard stop only guards against pathological weekday data.
        hard_stop = regen_from_date + timedelta(days=1500)
        while (
            (remaining > 0 if remaining is not None else current_date <= self.end_date)
            and current_date <= hard_stop
        ):
            if current_date in kept_dates:
                # A started lesson already sits on this date: it keeps its slot
                # (and its "No."), so advance the numbering past it.
                next_lesson_no += 1
                if remaining is not None:
                    remaining -= 1
                current_date += timedelta(days=1)
                continue

            weekday_num = current_date.weekday()
            matching_weekday = self.lesson_days.filtered(lambda w: w.sequence == weekday_num + 1)

            if matching_weekday:
                start_dt_utc = self._make_utc_datetime(current_date, self.lesson_start)
                end_dt_utc = self._make_utc_datetime(current_date, self.lesson_end)

                slide = lessons_by_no.get(next_lesson_no)
                slide_id = slide.id if slide else False
                next_lesson_no += 1

                vals = {
                    "group_id": self.id,
                    "weekday_id": matching_weekday[0].id,
                    "room_id": self.lesson_room.id,
                    "start_datetime": start_dt_utc,
                    "end_datetime": end_dt_utc,
                    "slide_id": slide_id,
                    "state": "scheduled",
                    "teacher_id": self.teacher_id.id if self.teacher_id else False,
                }
                timetable_entries.append((0, 0, vals))

                if remaining is not None:
                    remaining -= 1

            current_date += timedelta(days=1)

        if timetable_entries:
            self.write({"timetable_ids": timetable_entries})
            self._sync_end_date_to_schedule()
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "message": _("%s timetable entries regenerated (from %s)!", len(timetable_entries), regen_from_date),
                    "type": "success",
                    "sticky": False,
                },
            }

        raise UserError(_("No timetable entries were generated. Please check your settings."))

    def _sync_end_date_to_schedule(self):
        """Point end_date at the group's real last lesson. Only meaningful in
        lesson-count mode, where end_date is derived data: generation may run
        past a stale end_date (or stop before it), so after (re)generating the
        stored date is realigned with the schedule that actually exists."""
        self.ensure_one()
        if self._planned_lesson_total() is None:
            return
        last = self.env["edu.timetable"].search(
            [("group_id", "=", self.id), ("state", "!=", "cancelled")],
            order="start_datetime desc",
            limit=1,
        )
        if last:
            last_date = fields.Datetime.context_timestamp(
                self, last.start_datetime
            ).date()
            if self.end_date != last_date:
                self.end_date = last_date

    def action_generate_timetable(self):
        self.ensure_one()
        self._ensure_end_date()

        if not self.lesson_days:
            raise UserError(_("Please select lesson days before generating timetable."))
        if not self.lesson_room:
            raise UserError(_("Please select a lesson room before generating timetable."))
        if not self.start_date or not self.end_date:
            raise UserError(_("Please set start and end dates before generating timetable."))
        if self.start_date > self.end_date:
            raise UserError(_("End date must not be before start date."))
        if not self.lesson_start or not self.lesson_end:
            raise UserError(_("Please set lesson start and end times."))
        if self.lesson_start >= self.lesson_end:
            raise UserError(_("Lesson end time must be after start time."))
        if not self.lesson_room.active:
            raise UserError(_(
                "%s xonasi arxivlangan — jadval unda ko'rinmaydi. Avval "
                "guruhga faol xonani tanlang.", self.lesson_room.name))

        lessons_by_no = self._get_lessons_by_no()

        existing_entries = self.env["edu.timetable"].search([("group_id", "=", self.id)])
        if existing_entries:
            existing_entries.unlink()

        timetable_entries = []
        current_date = self.start_date
        # The Nth day of the group carries "No." = start_lesson_number + (N-1),
        # and we attach the slide whose lesson_no matches that "No.".
        next_lesson_no = max(self.start_lesson_number or 1, 1)
        # Planned total respects the start offset: starting at lesson 109 of a
        # 144-lesson course generates 36 entries (No. 109..144), not 144.
        remaining = self._planned_lesson_total()
        if remaining is not None and remaining <= 0:
            raise UserError(_(
                "Boshlangan dars (%s) jami darslar sonidan (%s) katta yoki teng emas — "
                "jadval yaratilmaydi.", next_lesson_no, self.lesson_count))

        # Same rule as regenerate: in lesson-count mode the plan drives the
        # loop and a stale/too-early end_date must not truncate the schedule.
        hard_stop = self.start_date + timedelta(days=1500)
        while (
            (remaining > 0 if remaining is not None else current_date <= self.end_date)
            and current_date <= hard_stop
        ):
            weekday_num = current_date.weekday()
            matching_weekday = self.lesson_days.filtered(lambda w: w.sequence == weekday_num + 1)

            if matching_weekday:
                start_dt_utc = self._make_utc_datetime(current_date, self.lesson_start)
                end_dt_utc = self._make_utc_datetime(current_date, self.lesson_end)

                slide = lessons_by_no.get(next_lesson_no)
                slide_id = slide.id if slide else False
                next_lesson_no += 1

                vals = {
                    "group_id": self.id,
                    "weekday_id": matching_weekday[0].id,
                    "room_id": self.lesson_room.id,
                    "start_datetime": start_dt_utc,
                    "end_datetime": end_dt_utc,
                    "slide_id": slide_id,
                    "state": "scheduled",
                    "teacher_id": self.teacher_id.id if self.teacher_id else False,
                }
                timetable_entries.append((0, 0, vals))

                if remaining is not None:
                    remaining -= 1

            current_date += timedelta(days=1)

        if timetable_entries:
            self.write({"timetable_ids": timetable_entries})
            self._sync_end_date_to_schedule()
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "message": _("%s timetable entries generated successfully!", len(timetable_entries)),
                    "type": "success",
                    "sticky": False,
                },
            }

        raise UserError(_("No timetable entries were generated. Please check your settings."))
