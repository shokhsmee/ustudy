"""Data provider for the "Jadval" operational workspace.

This model owns NO data of its own: every number it returns is read from
edu.timetable (lessons) and dars.jadvali.booking (majlis / konsultatsiya /
mehmon), and the room-occupancy helpers are reused from dars.jadvali.board.
The existing schedules keep working exactly as before — this app is an extra
read/plan surface on top of them.
"""

from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.ustudy_group.models.edu_group import CLOSED_GROUP_STATES
from odoo.addons.ustudy_dars_jadvali.models.booking import PURPOSE_LABELS

# The grid always shows the working day 08:00-22:00 and only stretches when an
# event actually falls outside it, so nothing is ever clipped (same rule as
# the Jadval doskasi board).
GRID_START_MIN = 8 * 60
GRID_END_MIN = 22 * 60

# A room only counts as "bo'sh" when a whole lesson fits in the gap.
FREE_SLOT_MINUTES = 90
# "keyingi ... daqiqada" hint on the first stat tile
SOON_MINUTES = 90

UZ_DAY_SHORT = ["Du", "Se", "Chor", "Pay", "Ju", "Sha", "Yak"]
UZ_DAY_FULL = [
    "Dushanba", "Seshanba", "Chorshanba", "Payshanba",
    "Juma", "Shanba", "Yakshanba",
]
UZ_MONTHS_SHORT = [
    "yan", "fev", "mar", "apr", "may", "iyun",
    "iyul", "avg", "sen", "okt", "noy", "dek",
]
UZ_MONTHS_FULL = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
]

LESSON_STATE_LABELS = {
    "scheduled": "Rejalashtirilgan",
    "in_progress": "Davom etmoqda",
    "completed": "O'tildi",
}

TYPE_OPTIONS = [
    ("dars", "Dars"),
    ("majlis", "Majlis"),
    ("konsultatsiya", "Konsultatsiya"),
    ("mehmon", "Mehmon uchun"),
]


def _hhmm(minutes):
    return "%02d:%02d" % (int(minutes) // 60, int(minutes) % 60)


def _short_date(day):
    return "%d %s." % (day.day, UZ_MONTHS_SHORT[day.month - 1])


class JadvalWorkspace(models.AbstractModel):
    _name = "jadval.workspace"
    _description = "Jadval operatsion maydoni (kun / hafta / xonalar)"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @api.model
    def _local(self, record, value):
        return fields.Datetime.context_timestamp(record, value) if value else None

    @api.model
    def _minutes(self, local_dt):
        return local_dt.hour * 60 + local_dt.minute

    @api.model
    def _now(self):
        """(today, minutes-from-midnight) in the user's timezone."""
        local = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        return local.date(), local.hour * 60 + local.minute

    @api.model
    def _rooms(self, params):
        Room = self.env["edu.room"]
        room_id = params.get("room_id")
        rooms = Room.browse(int(room_id)) if room_id else Room.search([("active", "=", True)])
        return rooms.sorted(lambda r: (r.sequence or 0, r.id))

    @api.model
    def _student_counts(self, group_ids):
        """{group_id: active students} in one query — reading student_count per
        lesson would recompute it for every card on the grid."""
        if not group_ids:
            return {}
        rows = self.env["edu.group.student"]._read_group(
            [("group_id", "in", list(group_ids)), ("state", "=", "active")],
            groupby=["group_id"],
            aggregates=["__count"],
        )
        return {group.id: count for group, count in rows}

    # ------------------------------------------------------------------
    # event collection
    # ------------------------------------------------------------------
    @api.model
    def _lesson_events(self, date_from, date_to, params, room_ids):
        wanted_type = params.get("type") or ""
        if wanted_type and wanted_type != "dars":
            return []

        domain = [
            ("state", "!=", "cancelled"),
            ("group_id.active", "=", True),
            # finished/cancelled groups have left the schedule
            ("group_id.state", "not in", list(CLOSED_GROUP_STATES)),
            ("room_id", "in", room_ids),
            # start_date is the UTC date, so a local day can sit one day off
            ("start_date", ">=", date_from - timedelta(days=1)),
            ("start_date", "<=", date_to + timedelta(days=1)),
        ]
        if params.get("teacher_id"):
            domain.append(("teacher_id", "=", int(params["teacher_id"])))
        if params.get("course_id"):
            domain.append(("group_id.course_id", "=", int(params["course_id"])))
        if params.get("group_id"):
            domain.append(("group_id", "=", int(params["group_id"])))
        if params.get("status"):
            domain.append(("state", "=", params["status"]))

        lessons = self.env["edu.timetable"].search(domain, order="start_datetime asc")
        students = self._student_counts(lessons.mapped("group_id").ids)

        events = []
        for lesson in lessons:
            start = self._local(lesson, lesson.start_datetime)
            end = self._local(lesson, lesson.end_datetime)
            if not start or not end:
                continue
            day = start.date()
            if not (date_from <= day <= date_to):
                continue
            group = lesson.group_id
            start_min = self._minutes(start)
            # an event running past midnight is clamped to the day end so it
            # can never spill over the grid
            end_min = self._minutes(end) if end.date() == day else 24 * 60
            if end_min <= start_min:
                end_min = start_min + 60
            events.append({
                "uid": "l%d" % lesson.id,
                "kind": "lesson",
                "type": "dars",
                "type_label": "Dars",
                "title": group.course_id.name or group.name or "Dars",
                "code": group.name or "",
                # sudo: the board only needs the teacher's name, and non-HR
                # users may not read hr.employee directly
                "teacher": lesson.teacher_id.sudo().name or group.teacher_id.sudo().name or "",
                "room_id": lesson.room_id.id,
                "room_name": lesson.room_id.name or "",
                "capacity": lesson.room_id.capacity or 0,
                "date": fields.Date.to_string(day),
                "weekday": day.weekday(),
                "start_min": start_min,
                "end_min": end_min,
                "time_label": "%s–%s" % (_hhmm(start_min), _hhmm(end_min)),
                "state": lesson.state,
                "state_label": LESSON_STATE_LABELS.get(lesson.state, lesson.state or ""),
                "students": students.get(group.id, 0),
                "group_id": group.id,
                "notes": lesson.notes or "",
                "tone": "lesson",
                "conflict": False,
            })
        return events

    @api.model
    def _booking_events(self, date_from, date_to, params, room_ids):
        wanted_type = params.get("type") or ""
        if wanted_type == "dars":
            return []
        # bookings carry no group/teacher/course/lesson-state, so those
        # filters hide them (same rule as the Jadval doskasi board)
        if params.get("teacher_id") or params.get("course_id") \
                or params.get("group_id") or params.get("status"):
            return []

        # _make_utc_datetime lives on edu.group (ustudy_group extends it in
        # edu_timetable.py), same call the Jadval doskasi board uses
        Group = self.env["edu.group"]
        domain = [
            ("room_id", "in", room_ids),
            ("start_datetime", ">=", Group._make_utc_datetime(date_from, 0.0)),
            ("start_datetime", "<", Group._make_utc_datetime(
                date_to + timedelta(days=1), 0.0)),
        ]
        if wanted_type:
            domain.append(("purpose", "=", wanted_type))

        events = []
        for booking in self.env["dars.jadvali.booking"].search(domain, order="start_datetime asc"):
            start = self._local(booking, booking.start_datetime)
            end = self._local(booking, booking.end_datetime)
            if not start or not end:
                continue
            day = start.date()
            if not (date_from <= day <= date_to):
                continue
            start_min = self._minutes(start)
            end_min = self._minutes(end) if end.date() == day else 24 * 60
            if end_min <= start_min:
                end_min = start_min + 60
            label = PURPOSE_LABELS.get(booking.purpose, booking.purpose or "")
            events.append({
                "uid": "b%d" % booking.id,
                "kind": "booking",
                "type": booking.purpose,
                "type_label": label,
                "title": booking.note or label,
                "code": booking.user_id.sudo().name or "",
                "teacher": "",
                "room_id": booking.room_id.id,
                "room_name": booking.room_id.name or "",
                "capacity": booking.room_id.capacity or 0,
                "date": fields.Date.to_string(day),
                "weekday": day.weekday(),
                "start_min": start_min,
                "end_min": end_min,
                "time_label": "%s–%s" % (_hhmm(start_min), _hhmm(end_min)),
                "state": "booked",
                "state_label": "Band qilingan",
                "students": 0,
                "group_id": False,
                "booking_id": booking.id,
                "notes": booking.note or "",
                "tone": "internal",
                "conflict": False,
            })
        return events

    @api.model
    def _mark_conflicts(self, events):
        """Two events holding the same room at the same time. The schedule
        guards normally prevent this, but data predating them (and cross-model
        overlaps) does exist — the board must show it rather than hide it."""
        by_room = {}
        for event in events:
            by_room.setdefault((event["room_id"], event["date"]), []).append(event)

        conflicts = []
        for (_room_id, _day), items in by_room.items():
            items.sort(key=lambda e: (e["start_min"], e["end_min"]))
            for i, event in enumerate(items):
                for other in items[i + 1:]:
                    if other["start_min"] >= event["end_min"]:
                        break
                    event["conflict"] = other["conflict"] = True
                    event["tone"] = other["tone"] = "conflict"
                    conflicts.append({
                        "room_name": event["room_name"],
                        "date": event["date"],
                        "day_label": "%s, %s" % (
                            UZ_DAY_FULL[event["weekday"]],
                            _short_date(fields.Date.to_date(event["date"])),
                        ),
                        "first": {
                            "uid": event["uid"], "title": event["title"],
                            "code": event["code"], "time_label": event["time_label"],
                        },
                        "second": {
                            "uid": other["uid"], "title": other["title"],
                            "code": other["code"], "time_label": other["time_label"],
                        },
                    })
        return conflicts

    @api.model
    def _assign_lanes(self, events, column_key):
        """Side-by-side placement for events sharing a column: each cluster of
        overlapping events is split into lanes so no card hides another."""
        by_col = {}
        for event in events:
            by_col.setdefault(event[column_key], []).append(event)

        for items in by_col.values():
            items.sort(key=lambda e: (e["start_min"], -e["end_min"]))
            cluster = []
            cluster_end = None
            for event in items:
                if cluster and event["start_min"] >= cluster_end:
                    self._close_cluster(cluster)
                    cluster = []
                    cluster_end = None
                lanes_end = {}
                for placed in cluster:
                    lanes_end[placed["lane"]] = max(
                        lanes_end.get(placed["lane"], 0), placed["end_min"])
                lane = 0
                while lanes_end.get(lane, 0) > event["start_min"]:
                    lane += 1
                event["lane"] = lane
                cluster.append(event)
                cluster_end = max(cluster_end or 0, event["end_min"])
            self._close_cluster(cluster)

    @api.model
    def _close_cluster(self, cluster):
        if not cluster:
            return
        lanes = max(event["lane"] for event in cluster) + 1
        for event in cluster:
            event["lanes"] = lanes

    # ------------------------------------------------------------------
    # occupancy
    # ------------------------------------------------------------------
    @api.model
    def _merge(self, intervals):
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return merged

    @api.model
    def _room_occupancy(self, day, rooms):
        """Per-room busy minutes + free windows for one day, reusing the
        Jadval doskasi helpers so both screens agree on what "bo'sh" means."""
        Board = self.env["dars.jadvali.board"]
        busy = Board._busy_intervals(day, day, rooms.ids)
        free = Board._free_windows(day, day, rooms.ids, min_minutes=FREE_SLOT_MINUTES)

        free_by_room = {}
        for window in free:
            free_by_room.setdefault(window["room_id"], []).append({
                "start_min": window["start_min"],
                "end_min": window["end_min"],
                "label": window["label"],
                "fits": window["fits"],
            })

        out = {}
        span = GRID_END_MIN - GRID_START_MIN
        for room in rooms:
            intervals = [
                (max(start, GRID_START_MIN), min(end, GRID_END_MIN))
                for start, end in busy.get((room.id, day), [])
            ]
            minutes = sum(
                end - start for start, end in self._merge(
                    [(s, e) for s, e in intervals if e > s])
            )
            out[room.id] = {
                "busy_minutes": minutes,
                "occupancy": int(round(minutes * 100.0 / span)) if span else 0,
                "free_windows": free_by_room.get(room.id, []),
            }
        return out

    # ------------------------------------------------------------------
    # stat tiles
    # ------------------------------------------------------------------
    @api.model
    def _stats(self, day, rooms, occupancy, day_events, conflicts, today, now_min):
        is_today = day == today
        lessons = [e for e in day_events if e["kind"] == "lesson"]
        meetings = [e for e in day_events if e["kind"] == "booking"]

        if is_today:
            active = len([
                e for e in day_events
                if e["start_min"] <= now_min < e["end_min"]
            ])
            soon = len([
                e for e in day_events
                if now_min <= e["start_min"] <= now_min + SOON_MINUTES
            ])
            lessons_hint = "%d ta keyingi %d daqiqada" % (soon, SOON_MINUTES)
            active_hint = "soat %s holatiga" % _hhmm(now_min)
        else:
            active = 0
            lessons_hint = "%s kuni jami" % _short_date(day)
            active_hint = "boshqa kun tanlangan"

        free_rooms = len([
            room for room in rooms
            if occupancy.get(room.id, {}).get("free_windows")
        ])
        busy_rooms = len({e["room_id"] for e in day_events})

        return [
            {
                "key": "lessons",
                "label": "Bugungi darslar" if is_today else "Kundagi darslar",
                "value": len(lessons),
                "hint": lessons_hint,
                "icon": "fa-graduation-cap",
                "tone": "green",
            },
            {
                "key": "active",
                "label": "Faol hozir",
                "value": active,
                "hint": active_hint,
                "icon": "fa-clock-o",
                "tone": "mint",
            },
            {
                "key": "free_rooms",
                "label": "Bo'sh xonalar",
                "value": free_rooms,
                "hint": "band qilishga tayyor",
                "icon": "fa-building-o",
                "tone": "blue",
            },
            {
                "key": "busy_rooms",
                "label": "Band xonalar",
                "value": busy_rooms,
                "hint": "dars va uchrashuvlar",
                "icon": "fa-map-marker",
                "tone": "amber",
            },
            {
                "key": "meetings",
                "label": "Uchrashuvlar",
                "value": len(meetings),
                "hint": "kampus bo'ylab",
                "icon": "fa-users",
                "tone": "violet",
            },
            {
                "key": "conflicts",
                "label": "Konfliktlar",
                "value": len(conflicts),
                "hint": "yechim talab qiladi",
                "icon": "fa-exclamation-triangle",
                "tone": "rose",
                "drill": True,
            },
        ]

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------
    @api.model
    def get_workspace(self, params=None):
        params = params or {}
        today, now_min = self._now()
        day = fields.Date.to_date(params.get("date")) or today
        view = params.get("view") or "day"
        if view not in ("day", "week", "rooms"):
            view = "day"

        monday = day - timedelta(days=day.weekday())
        sunday = monday + timedelta(days=6)
        date_from, date_to = (monday, sunday) if view == "week" else (day, day)

        rooms = self._rooms(params)
        room_ids = rooms.ids

        events = []
        if room_ids:
            events = (
                self._lesson_events(date_from, date_to, params, room_ids)
                + self._booking_events(date_from, date_to, params, room_ids)
            )
        conflicts = self._mark_conflicts(events)

        # the day's own numbers stay campus-wide (the tiles are a pulse, not a
        # filtered report), so they are collected without the UI filters
        day_events = events
        if view == "week":
            day_iso = fields.Date.to_string(day)
            day_events = [e for e in events if e["date"] == day_iso]
        day_conflicts = [c for c in conflicts if c["date"] == fields.Date.to_string(day)]

        all_rooms = self.env["edu.room"].search([("active", "=", True)]).sorted(
            lambda r: (r.sequence or 0, r.id))
        occupancy = self._room_occupancy(day, all_rooms) if all_rooms else {}

        # grid window: the fixed working day, stretched by anything outside it
        start_min, end_min = GRID_START_MIN, GRID_END_MIN
        for event in events:
            start_min = min(start_min, (event["start_min"] // 60) * 60)
            end_min = max(end_min, -(-event["end_min"] // 60) * 60)

        if view == "week":
            column_key = "date"
            columns = []
            for offset in range(7):
                column_day = monday + timedelta(days=offset)
                iso = fields.Date.to_string(column_day)
                columns.append({
                    "key": iso,
                    "title": UZ_DAY_SHORT[column_day.weekday()],
                    "subtitle": _short_date(column_day),
                    "status": "conflict" if any(
                        c["date"] == iso for c in conflicts) else "free",
                    "is_today": column_day == today,
                    "date": iso,
                })
        else:
            column_key = "room_id"
            columns = []
            for room in rooms:
                info = occupancy.get(room.id, {})
                has_conflict = any(
                    e["room_id"] == room.id and e["conflict"] for e in events)
                columns.append({
                    "key": room.id,
                    "title": room.name or "",
                    "subtitle": "%d o'rin" % (room.capacity or 0),
                    "status": (
                        "conflict" if has_conflict
                        else "free" if info.get("free_windows") else "busy"
                    ),
                    "is_today": False,
                    "room_id": room.id,
                })

        for event in events:
            event["col"] = event["date"] if view == "week" else event["room_id"]
            event["lane"] = 0
            event["lanes"] = 1
        self._assign_lanes(events, "col")

        return {
            "view": view,
            "date": fields.Date.to_string(day),
            "today": fields.Date.to_string(today),
            "now_min": now_min,
            "day_label": "%s, %s" % (UZ_DAY_SHORT[day.weekday()], _short_date(day)),
            "day_label_full": "%s, %d %s" % (
                UZ_DAY_FULL[day.weekday()], day.day, UZ_MONTHS_FULL[day.month - 1]),
            "range_label": "%s — %s %d" % (
                _short_date(monday), _short_date(sunday), sunday.year),
            "week": [
                {
                    "date": fields.Date.to_string(monday + timedelta(days=offset)),
                    "dow": UZ_DAY_SHORT[offset],
                    "day": (monday + timedelta(days=offset)).day,
                    "is_today": (monday + timedelta(days=offset)) == today,
                    "is_selected": (monday + timedelta(days=offset)) == day,
                }
                for offset in range(7)
            ],
            "columns": columns,
            "column_key": column_key,
            "events": events,
            "conflicts": day_conflicts if view != "week" else conflicts,
            "grid": {
                "start_min": start_min,
                "end_min": end_min,
                "hours": [
                    {"min": minute, "label": _hhmm(minute)}
                    for minute in range(start_min, end_min + 1, 60)
                ],
            },
            "rooms_view": [
                {
                    "id": room.id,
                    "name": room.name or "",
                    "capacity": room.capacity or 0,
                    "occupancy": occupancy.get(room.id, {}).get("occupancy", 0),
                    "busy_label": "%d s %d daq" % (
                        occupancy.get(room.id, {}).get("busy_minutes", 0) // 60,
                        occupancy.get(room.id, {}).get("busy_minutes", 0) % 60,
                    ),
                    "events": sorted(
                        [
                            {
                                "uid": e["uid"], "title": e["title"], "code": e["code"],
                                "time_label": e["time_label"], "tone": e["tone"],
                                "type_label": e["type_label"],
                            }
                            for e in day_events if e["room_id"] == room.id
                        ],
                        key=lambda e: e["time_label"],
                    ),
                    "free_windows": occupancy.get(room.id, {}).get("free_windows", []),
                }
                for room in all_rooms
            ],
            "stats": self._stats(
                day, all_rooms, occupancy, day_events, day_conflicts, today, now_min),
            "filter_options": self._filter_options(),
            "min_slot_minutes": FREE_SLOT_MINUTES,
        }

    @api.model
    def _filter_options(self):
        groups = self.env["edu.group"].search(
            [("active", "=", True), ("state", "not in", list(CLOSED_GROUP_STATES))],
            order="name",
        )
        rooms = self.env["edu.room"].search([("active", "=", True)]).sorted(
            lambda r: (r.sequence or 0, r.id))
        courses = groups.mapped("course_id").sorted("name")
        teachers = (
            groups.mapped("teacher_id")
            | self.env["edu.timetable"].search([
                ("group_id.active", "=", True),
                ("group_id.state", "not in", list(CLOSED_GROUP_STATES)),
            ]).mapped("teacher_id")
        ).sudo()  # names only
        return {
            "rooms": [{"id": r.id, "name": r.name} for r in rooms],
            "courses": [{"id": c.id, "name": c.name} for c in courses],
            "teachers": [{"id": t.id, "name": t.name} for t in teachers.sorted("name")],
            "groups": [{"id": g.id, "name": g.name} for g in groups],
            "types": [{"id": key, "name": label} for key, label in TYPE_OPTIONS],
            "statuses": [
                {"id": key, "name": label}
                for key, label in LESSON_STATE_LABELS.items()
            ],
        }

    # ------------------------------------------------------------------
    # event drawer
    # ------------------------------------------------------------------
    @api.model
    def get_event_detail(self, uid):
        if uid.startswith("b"):
            return self._booking_detail(int(uid[1:]))
        return self._lesson_detail(int(uid[1:]))

    @api.model
    def _lesson_detail(self, lesson_id):
        lesson = self.env["edu.timetable"].browse(lesson_id)
        if not lesson.exists():
            return False
        group = lesson.group_id
        start = self._local(lesson, lesson.start_datetime)
        end = self._local(lesson, lesson.end_datetime)
        day = start.date()
        snapshot = self.env["dars.jadvali.board"]._group_snapshot(group)
        students = self._student_counts([group.id]).get(group.id, 0)

        rows = [
            {"label": "Kurs", "value": group.course_id.name or "—"},
            {"label": "Guruh", "value": group.name or "—"},
            {"label": "O'qituvchi",
             "value": lesson.teacher_id.sudo().name or group.teacher_id.sudo().name or "—"},
            {"label": "Ishtirokchilar", "value": "%d talaba" % students},
            {"label": "Dars raqami", "value": "%d-dars" % (lesson.lesson_sequence or 0)},
            {"label": "Reja / Fakt",
             "value": "%s · %s" % (snapshot["module_reja"], snapshot["module_fakt"])},
        ]
        return {
            "uid": "l%d" % lesson.id,
            "kind": "lesson",
            "type_label": "Dars",
            "state_label": LESSON_STATE_LABELS.get(lesson.state, lesson.state or ""),
            "tone": "lesson",
            "title": group.course_id.name or group.name or "Dars",
            # title carries the course, so the subtitle names the group and,
            # when set, its teacher
            "subtitle": " · ".join(filter(None, [
                group.name or "",
                lesson.teacher_id.sudo().name or group.teacher_id.sudo().name or "",
            ])),
            "when_label": "%s, %s" % (UZ_DAY_SHORT[day.weekday()], _short_date(day)),
            "when_time": "%s — %s" % (
                _hhmm(self._minutes(start)), _hhmm(self._minutes(end))),
            "where_label": lesson.room_id.name or "—",
            "where_hint": "%d ishtirokchi" % students,
            "rows": rows,
            "notes": lesson.notes or "",
            "group_id": group.id,
            "timetable_ids": [lesson.id],
        }

    @api.model
    def _booking_detail(self, booking_id):
        booking = self.env["dars.jadvali.booking"].browse(booking_id)
        if not booking.exists():
            return False
        start = self._local(booking, booking.start_datetime)
        end = self._local(booking, booking.end_datetime)
        day = start.date()
        label = PURPOSE_LABELS.get(booking.purpose, booking.purpose or "")
        return {
            "uid": "b%d" % booking.id,
            "kind": "booking",
            "type_label": label,
            "state_label": "Band qilingan",
            "tone": "internal",
            "title": booking.note or label,
            "subtitle": label,
            "when_label": "%s, %s" % (UZ_DAY_SHORT[day.weekday()], _short_date(day)),
            "when_time": "%s — %s" % (
                _hhmm(self._minutes(start)), _hhmm(self._minutes(end))),
            "where_label": booking.room_id.name or "—",
            "where_hint": "%d o'rin" % (booking.room_id.capacity or 0),
            "rows": [
                {"label": "Turi", "value": label},
                {"label": "Xona", "value": booking.room_id.name or "—"},
                {"label": "Band qilgan", "value": booking.user_id.sudo().name or "—"},
            ],
            "notes": booking.note or "",
            "booking_id": booking.id,
        }
