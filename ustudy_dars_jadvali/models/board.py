from datetime import timedelta
from math import ceil

from odoo import api, fields, models

from odoo.addons.ustudy_group.models.edu_group import CLOSED_GROUP_STATES

from .booking import PURPOSE_LABELS

# 30-minute board grid. The window is FIXED: every day shows 08:00-22:00
# (user request 2026-08-09, replacing the old dynamic earliest-to-latest
# window) and only stretches beyond that when a lesson actually falls outside
# it, so nothing is ever clipped. A lesson card sits on the row that contains
# its local start time and spans (rowspan) every 30-min row up to its end
# time, so a 10:30-12:00 lesson renders exactly over 10:30-12:00.
FIXED_START_MIN = 8 * 60            # 08:00
FIXED_END_MIN = 22 * 60             # 22:00
SLOT_MINUTES = 30

# Shortest bookable window (user rule 2026-08-24): a room counts as
# "bo'sh" only when at least one 1,5-hour gap fits somewhere in the
# period, since that is the length of a normal lesson.
FREE_SLOT_MINUTES = 90

# Mon/Wed/Fri = toq (odd) block, Tue/Thu/Sat = juft (even) block. Sunday is
# not part of the board.
PARITY_BY_WEEKDAY = {0: "toq", 2: "toq", 4: "toq", 1: "juft", 3: "juft", 5: "juft"}
PARITY_LABELS = {"toq": "Dush / Chor / Jum", "juft": "Sesh / Pay / Shan"}
BLOCK_WEEKDAYS = {"toq": [0, 2, 4], "juft": [1, 3, 5]}

# Cards are grouped per 3-day block, so a card that does NOT run on every day
# of its block (a one-off/extra lesson, a make-up moved to another hour) is
# indistinguishable from a regular one. Those cards get a day badge.
UZ_DAY_NAMES = {
    0: "Dushanba", 1: "Seshanba", 2: "Chorshanba",
    3: "Payshanba", 4: "Juma", 5: "Shanba",
}
UZ_DAY_SHORT = {0: "Du", 1: "Se", 2: "Chor", 3: "Pay", 4: "Jum", 5: "Shan"}

UZ_MONTHS = [
    "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
    "Iyul", "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr",
]


class DarsJadvaliBoard(models.AbstractModel):
    _name = "dars.jadvali.board"
    _description = "Dars Jadvali Board (room/time schedule with Reja/Fakt)"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @api.model
    def _slot_label(self, idx, day_start_min):
        start = day_start_min + idx * SLOT_MINUTES
        end = start + SLOT_MINUTES
        return "%02d:%02d - %02d:%02d" % (start // 60, start % 60, end // 60, end % 60)

    @api.model
    def _slot_index(self, local_dt, day_start_min, day_end_min):
        minutes = local_dt.hour * 60 + local_dt.minute
        if day_start_min <= minutes < day_end_min:
            return (minutes - day_start_min) // SLOT_MINUTES
        return None

    @api.model
    def _slot_span(self, s_idx, start_local, end_local, day_start_min, day_end_min, slot_count):
        """How many 30-min rows the lesson covers from its start row (>= 1)."""
        if not end_local or end_local <= start_local:
            return 1
        end_min = end_local.hour * 60 + end_local.minute
        if end_local.date() != start_local.date():
            end_min = day_end_min
        end_idx = ceil((min(end_min, day_end_min) - day_start_min) / SLOT_MINUTES)
        return max(1, min(end_idx, slot_count) - s_idx)

    @api.model
    def _day_window(self, items):
        """Fixed grid window 08:00-22:00, stretched (floored/ceiled to 30 min)
        only when a lesson starts before 08:00 or ends after 22:00 so no card
        is ever hidden. items = [(entry, local_start, local_end, parity), ...]"""
        if not items:
            return FIXED_START_MIN, FIXED_END_MIN
        start_min = min(l.hour * 60 + l.minute for _, l, _, _ in items)
        day_start = min(FIXED_START_MIN, (start_min // SLOT_MINUTES) * SLOT_MINUTES)
        end_candidates = []
        for _, local, local_end, _ in items:
            m = local.hour * 60 + local.minute + SLOT_MINUTES  # at least one slot
            if local_end and local_end > local and local_end.date() == local.date():
                m = max(m, local_end.hour * 60 + local_end.minute)
            # overnight/broken end datetimes don't stretch the grid; the card
            # span is clamped to the window end instead (see _slot_span)
            end_candidates.append(m)
        day_end = ceil(max(end_candidates) / SLOT_MINUTES) * SLOT_MINUTES
        return day_start, max(FIXED_END_MIN, day_end, day_start + SLOT_MINUTES)

    @api.model
    def _group_snapshot(self, group):
        """Reja/Fakt numbers for one group.

        lessons_reja = planned total lessons (lesson_count, falling back to the
        actual generated timetable size). lessons_fakt = the lesson No. the
        group currently stands on: the lesson_sequence of its last held
        (in_progress/completed) entry. lesson_sequence honors
        group.start_lesson_number, so a mid-course group whose timetable
        records only start at No. 47 still shows fakt 50 after holding
        lessons 47-50 — counting held records would show 4.
        """
        Timetable = self.env["edu.timetable"]
        reja = group.lesson_count or Timetable.search_count(
            [("group_id", "=", group.id), ("state", "!=", "cancelled")]
        )
        last_done = Timetable.search(
            [("group_id", "=", group.id), ("state", "in", ("in_progress", "completed"))],
            order="start_datetime desc",
            limit=1,
        )
        fakt = (
            last_done.lesson_sequence
            if last_done
            else max(group.start_lesson_number or 1, 1) - 1
        )
        # Card shows modules, not raw lesson counts (user request 2026-08-17):
        # Reja "12 ta modul" = total lessons / lessons_per_module, Fakt
        # "9-modul, 7-dars" = where lesson No. `fakt` falls in that grid.
        lpm = self.env["edu.config"].get_config().lessons_per_module or 12
        module_reja = "%d ta modul" % ceil(reja / lpm) if reja else "0 ta modul"
        if fakt > 0:
            module_fakt = "%d-modul, %d-dars" % (
                (fakt - 1) // lpm + 1, (fakt - 1) % lpm + 1)
        else:
            module_fakt = "—"
        lines = group.student_line_ids
        students = len(lines.filtered(lambda l: l.state == "active"))
        # "Probniy" (trial students) has no dedicated state on
        # edu.group.student yet; counted as the non-active, non-cancelled
        # lines so a future 'trial' state shows up here automatically.
        probniy = len(lines.filtered(lambda l: l.state not in ("active", "cancelled")))
        return {
            "group_id": group.id,
            "group_name": group.name,
            # sudo: non-HR users may not read hr.employee directly (the public
            # profile lacks custom fields like pbx_extension/finance_* that
            # prefetch pulls in); the board only shows the name.
            # card title = group name only (course name/duration dropped by
            # user request 2026-07-29)
            "course": group.name,
            "teacher": group.teacher_id.sudo().name or "",
            "lessons_reja": reja,
            "lessons_fakt": fakt,
            "module_reja": module_reja,
            "module_fakt": module_fakt,
            "probniy": probniy,
            "students": students,
        }

    # ------------------------------------------------------------------
    # room occupancy: free windows + period stats
    # ------------------------------------------------------------------
    @api.model
    def _busy_intervals(self, date_from, date_to, room_ids):
        """{(room_id, local_date): [(start_min, end_min), ...]} — everything
        that holds a room in the period. Mirrors the room-conflict guards:
        lessons of closed/archived groups don't hold a room, bookings do.
        Group/teacher filters are deliberately NOT applied — a room stays busy
        no matter which group the board is currently showing."""
        busy = {}
        if not room_ids:
            return busy

        def add(room_id, local, local_end):
            if not local or not local_end or local_end <= local:
                return
            day = local.date()
            start = local.hour * 60 + local.minute
            end = (
                local_end.hour * 60 + local_end.minute
                if local_end.date() == day
                else 24 * 60
            )
            busy.setdefault((room_id, day), []).append((start, end))

        # stored start_date is the UTC date, so a lesson can sit one day off
        # its local date; search one day wider and bucket by the local date
        lessons = self.env["edu.timetable"].search([
            ("state", "!=", "cancelled"),
            ("group_id.active", "=", True),
            ("group_id.state", "not in", list(CLOSED_GROUP_STATES)),
            ("room_id", "in", room_ids),
            ("start_date", ">=", date_from - timedelta(days=1)),
            ("start_date", "<=", date_to + timedelta(days=1)),
        ])
        for lesson in lessons:
            add(
                lesson.room_id.id,
                fields.Datetime.context_timestamp(lesson, lesson.start_datetime),
                fields.Datetime.context_timestamp(lesson, lesson.end_datetime)
                if lesson.end_datetime else None,
            )

        Group = self.env["edu.group"]
        bookings = self.env["dars.jadvali.booking"].search([
            ("room_id", "in", room_ids),
            ("start_datetime", ">=", Group._make_utc_datetime(date_from, 0.0)),
            ("start_datetime", "<", Group._make_utc_datetime(
                date_to + timedelta(days=1), 0.0)),
        ])
        for bk in bookings:
            add(
                bk.room_id.id,
                fields.Datetime.context_timestamp(bk, bk.start_datetime),
                fields.Datetime.context_timestamp(bk, bk.end_datetime)
                if bk.end_datetime else None,
            )
        return busy

    @api.model
    def _free_windows(self, date_from, date_to, room_ids, min_minutes=FREE_SLOT_MINUTES):
        """Every gap of at least `min_minutes` inside the 08:00-22:00 board day,
        per room and per day (Sunday is not on the board)."""
        busy = self._busy_intervals(date_from, date_to, room_ids)
        rooms = self.env["edu.room"].browse(room_ids)
        info = {r.id: (r.name, r.capacity) for r in rooms}

        windows = []
        day = date_from
        while day <= date_to:
            if day.weekday() == 6:
                day += timedelta(days=1)
                continue
            for rid in room_ids:
                cursor = FIXED_START_MIN
                for start, end in sorted(busy.get((rid, day), [])):
                    start = max(start, FIXED_START_MIN)
                    end = min(end, FIXED_END_MIN)
                    if start - cursor >= min_minutes:
                        windows.append((rid, day, cursor, start))
                    cursor = max(cursor, end)
                if FIXED_END_MIN - cursor >= min_minutes:
                    windows.append((rid, day, cursor, FIXED_END_MIN))
            day += timedelta(days=1)

        out = []
        for rid, day, start, end in windows:
            name, capacity = info.get(rid, ("", 0))
            out.append({
                "room_id": rid,
                "room_name": name,
                "capacity": capacity,
                "date": fields.Date.to_string(day),
                "weekday": day.weekday(),
                "day_label": "%s, %s" % (
                    UZ_DAY_NAMES[day.weekday()], day.strftime("%d.%m")),
                "start_min": start,
                "end_min": end,
                "label": "%02d:%02d - %02d:%02d" % (
                    start // 60, start % 60, end // 60, end % 60),
                # how many back-to-back lessons of min_minutes fit in the gap
                "fits": (end - start) // min_minutes,
            })
        return out

    @api.model
    def _period_stats(self, date_from, date_to, room_ids, lesson_domain):
        """The three mini-dashboard numbers for one period."""
        free = self._free_windows(date_from, date_to, room_ids)
        events = self.env["dars.jadvali.booking"].search_count([
            ("room_id", "in", room_ids),
            ("start_datetime", ">=",
             self.env["edu.group"]._make_utc_datetime(date_from, 0.0)),
            ("start_datetime", "<",
             self.env["edu.group"]._make_utc_datetime(
                 date_to + timedelta(days=1), 0.0)),
        ])
        groups = self.env["edu.timetable"]._read_group(
            lesson_domain + [
                ("start_date", ">=", date_from),
                ("start_date", "<=", date_to),
            ],
            groupby=["group_id"],
        )
        return {
            "free_rooms": len({w["room_id"] for w in free}),
            "free_windows": len(free),
            "events": events,
            "groups": len(groups),
        }

    @api.model
    def _seat_color(self, students, capacity):
        if capacity and students > capacity:
            return "red"
        if capacity and students == capacity:
            return "green"
        return "yellow"

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------
    @api.model
    def get_board_data(self, params=None):
        params = params or {}
        today = fields.Date.context_today(self)

        date_from = fields.Date.to_date(params.get("date_from")) or (
            today - timedelta(days=today.weekday())
        )
        date_to = fields.Date.to_date(params.get("date_to")) or (
            date_from + timedelta(days=5)
        )
        if date_to < date_from:
            date_from, date_to = date_to, date_from

        room_id = params.get("room_id") or False
        teacher_id = params.get("teacher_id") or False
        group_id = params.get("group_id") or False
        parity = params.get("parity") or False
        slot = params.get("slot")
        slot = int(slot) if slot not in (None, False, "") else False

        domain = [
            ("state", "!=", "cancelled"),
            ("group_id.active", "=", True),
            # A finished ("Tugallandi") or cancelled group has left the
            # schedule: whatever lessons survive on it (held ones keep their
            # attendance history, and future-dated leftovers do happen) must
            # not show up on the board any more.
            ("group_id.state", "not in", list(CLOSED_GROUP_STATES)),
            ("start_date", ">=", date_from),
            ("start_date", "<=", date_to),
        ]
        if room_id:
            domain.append(("room_id", "=", int(room_id)))
        if teacher_id:
            domain.append(("teacher_id", "=", int(teacher_id)))
        if group_id:
            domain.append(("group_id", "=", int(group_id)))

        entries = self.env["edu.timetable"].search(domain, order="start_datetime asc")

        # Rooms shown as columns: the filtered one, or every active room.
        Room = self.env["edu.room"]
        rooms = Room.browse(int(room_id)) if room_id else Room.search([("active", "=", True)])
        rooms = rooms.sorted(lambda r: (r.sequence or 0, r.id))
        room_infos = [{"id": r.id, "name": r.name, "capacity": r.capacity} for r in rooms]
        room_ids = [r.id for r in rooms]

        # ---- pre-pass: local times + parity/room filters, then the dynamic
        # grid window is derived from the surviving lessons (NOT the slot
        # filter, so slot indexes stay stable between requests)
        items = []
        for entry in entries:
            local = fields.Datetime.context_timestamp(entry, entry.start_datetime)
            p = PARITY_BY_WEEKDAY.get(local.weekday())
            if not p or (parity and p != parity):
                continue
            if entry.room_id.id not in room_ids:
                continue
            local_end = (
                fields.Datetime.context_timestamp(entry, entry.end_datetime)
                if entry.end_datetime
                else None
            )
            items.append((entry, local, local_end, p))

        # Non-lesson room bookings (majlis/konsultatsiya/mehmon) share the
        # grid. They carry no group/teacher, so those filters hide them.
        booking_items = []
        if not (group_id or teacher_id):
            utc_from = self.env["edu.group"]._make_utc_datetime(date_from, 0.0)
            utc_to = self.env["edu.group"]._make_utc_datetime(
                date_to + timedelta(days=1), 0.0
            )
            bookings = self.env["dars.jadvali.booking"].search(
                [
                    ("start_datetime", ">=", utc_from),
                    ("start_datetime", "<", utc_to),
                ],
                order="start_datetime asc",
            )
            for bk in bookings:
                local = fields.Datetime.context_timestamp(bk, bk.start_datetime)
                p = PARITY_BY_WEEKDAY.get(local.weekday())
                if not p or (parity and p != parity):
                    continue
                if bk.room_id.id not in room_ids:
                    continue
                local_end = (
                    fields.Datetime.context_timestamp(bk, bk.end_datetime)
                    if bk.end_datetime
                    else None
                )
                booking_items.append((bk, local, local_end, p))

        day_start_min, day_end_min = self._day_window(items + booking_items)
        slot_count = (day_end_min - day_start_min) // SLOT_MINUTES
        if slot is not False and not (0 <= slot < slot_count):
            slot = False

        # ---- bucket entries: (week_monday, parity, slot_idx, room) -> groups
        snapshots = {}  # group_id -> snapshot (computed once)
        regular_days = {}  # group_id -> {weekday indexes the group normally studies}
        buckets = {}    # (week, parity, slot, room) -> {group_id: {...}}
        week_keys = set()

        for entry, local, local_end, p in items:
            s_idx = self._slot_index(local, day_start_min, day_end_min)
            if s_idx is None:
                continue
            span = self._slot_span(
                s_idx, local, local_end, day_start_min, day_end_min, slot_count
            )
            if slot is not False:
                # time filter: keep lessons covering the picked half-hour and
                # render them on that single row (no rowspan to clip).
                if not (s_idx <= slot < s_idx + span):
                    continue
                s_idx, span = slot, 1

            monday = local.date() - timedelta(days=local.weekday())
            week_keys.add(monday)
            key = (monday, p, s_idx, entry.room_id.id)
            cell = buckets.setdefault(key, {})
            gid = entry.group_id.id
            if gid not in snapshots:
                snapshots[gid] = self._group_snapshot(entry.group_id)
                regular_days[gid] = {
                    (seq or 1) - 1
                    for seq in entry.group_id.lesson_days.mapped("sequence")
                }
            card = cell.setdefault(
                gid,
                dict(
                    snapshots[gid],
                    capacity=entry.room_id.capacity,
                    room_id=entry.room_id.id,
                    span=1,
                    timetable_ids=[],
                    dates=[],
                    weekdays=[],
                ),
            )
            card["span"] = max(card["span"], span)
            card["timetable_ids"].append(entry.id)
            card["dates"].append(local.strftime("%d.%m %H:%M"))
            card["weekdays"].append(local.weekday())

        for bk, local, local_end, p in booking_items:
            s_idx = self._slot_index(local, day_start_min, day_end_min)
            if s_idx is None:
                continue
            span = self._slot_span(
                s_idx, local, local_end, day_start_min, day_end_min, slot_count
            )
            if slot is not False:
                if not (s_idx <= slot < s_idx + span):
                    continue
                s_idx, span = slot, 1
            monday = local.date() - timedelta(days=local.weekday())
            week_keys.add(monday)
            key = (monday, p, s_idx, bk.room_id.id)
            cell = buckets.setdefault(key, {})
            cell["b%d" % bk.id] = {
                "kind": "booking",
                "booking_id": bk.id,
                # unique per-cell key: shares the card dict shape (t-key,
                # counted_groups) without ever colliding with a group id
                "group_id": "b%d" % bk.id,
                "purpose_label": PURPOSE_LABELS.get(bk.purpose, bk.purpose),
                "note": bk.note or "",
                "user": bk.user_id.sudo().name or "",
                "time": "%s - %s" % (
                    local.strftime("%H:%M"),
                    local_end.strftime("%H:%M") if local_end else "",
                ),
                "color": "booking",
                "span": span,
                "timetable_ids": [],
                "dates": [local.strftime("%d.%m %H:%M")],
                # a booking is always a single date (a weekly repeat creates
                # one record per week), so it ALWAYS names its day: sitting in
                # a 3-day block it would otherwise read as "every Du/Chor/Jum"
                "is_extra": True,
                "days_label": "%s · %s" % (
                    UZ_DAY_NAMES[local.weekday()], local.strftime("%d.%m")),
            }

        # ---- day badge for cards that don't cover their whole 3-day block.
        # A card aggregates a group's lessons for one (week, block, slot,
        # room), so an extra lesson added on a single day looks exactly like a
        # regular Du/Chor/Jum card. Compare the days the card actually runs on
        # against the group's own lesson days inside that block: when they
        # differ, the card names its day(s).
        for (monday, p, _s_idx, _rid), cell in buckets.items():
            block_days = BLOCK_WEEKDAYS[p]
            # a narrowed date range (a single day, half a week) cuts days out
            # of the block by itself — nothing can be called "extra" then
            full_block = all(
                date_from <= monday + timedelta(days=d) <= date_to
                for d in block_days
            )
            for card in cell.values():
                if card.get("kind") == "booking":
                    continue
                days = sorted(set(card.pop("weekdays", [])))
                regular = regular_days.get(card["group_id"]) or set()
                expected = [d for d in block_days if d in regular] or block_days
                card["is_extra"] = full_block and days != expected
                card["days_label"] = (
                    UZ_DAY_NAMES[days[0]] if len(days) == 1
                    else ", ".join(UZ_DAY_SHORT[d] for d in days)
                )

        # ---- assemble weeks -> blocks -> slot rows
        parities = [parity] if parity else ["toq", "juft"]
        slot_indexes = [slot] if slot is not False else list(range(slot_count))

        weeks = []
        for monday in sorted(week_keys) or [date_from - timedelta(days=date_from.weekday())]:
            saturday = monday + timedelta(days=5)
            blocks = []
            for p in parities:
                rows = []
                # per-room totals for this block
                totals = {
                    rid: {"lessons_reja": 0, "lessons_fakt": 0, "seats_reja": 0, "seats_fakt": 0}
                    for rid in room_ids
                }
                counted_groups = {rid: set() for rid in room_ids}
                # rowspan bookkeeping: a card spanning N rows renders one <td>
                # on its start row; the covered rows below emit skip-cells.
                open_until = {rid: 0 for rid in room_ids}
                open_cells = {rid: None for rid in room_ids}
                last_end = slot_indexes[-1] + 1
                for s_idx in slot_indexes:
                    cells = {}
                    for rid in room_ids:
                        cards = list(buckets.get((monday, p, s_idx, rid), {}).values())
                        for card in cards:
                            if card.get("kind") == "booking":
                                # preset color; no Reja/Fakt numbers to total
                                continue
                            card["color"] = self._seat_color(card["students"], card["capacity"])
                            t = totals[rid]
                            if card["group_id"] not in counted_groups[rid]:
                                counted_groups[rid].add(card["group_id"])
                                t["lessons_reja"] += card["lessons_reja"]
                                t["lessons_fakt"] += card["lessons_fakt"]
                                t["seats_reja"] += card["capacity"]
                                t["seats_fakt"] += card["students"]
                        if s_idx < open_until[rid]:
                            # row covered by a spanning card above; overlapping
                            # cards join that cell (rooms rarely overlap, but
                            # a broken rowspan would shift the whole table).
                            if cards:
                                oc = open_cells[rid]
                                oc["cards"].extend(cards)
                                new_end = min(
                                    max(open_until[rid], s_idx + max(c["span"] for c in cards)),
                                    last_end,
                                )
                                oc["rowspan"] = new_end - oc["start"]
                                open_until[rid] = new_end
                            cells[str(rid)] = {"skip": True}
                        else:
                            end = s_idx + (max(c["span"] for c in cards) if cards else 1)
                            end = min(end, last_end)
                            cell = {
                                "skip": False,
                                "cards": cards,
                                "rowspan": max(1, end - s_idx),
                                "start": s_idx,
                            }
                            if cards:
                                open_cells[rid] = cell
                                open_until[rid] = end
                            cells[str(rid)] = cell
                    rows.append({
                        "slot": self._slot_label(s_idx, day_start_min),
                        # slot start in minutes-from-midnight: the cell-click
                        # "add lesson" wizard prefills its start time from it
                        "start_min": day_start_min + s_idx * SLOT_MINUTES,
                        "cells": cells,
                    })

                block_total = {
                    k: sum(t[k] for t in totals.values())
                    for k in ("lessons_reja", "lessons_fakt", "seats_reja", "seats_fakt")
                }
                blocks.append({
                    "parity": p,
                    "label": PARITY_LABELS[p],
                    "rows": rows,
                    "room_totals": {str(rid): totals[rid] for rid in room_ids},
                    "total": block_total,
                })

            weeks.append({
                "month": "%s %s" % (UZ_MONTHS[monday.month - 1], monday.year),
                "label": "%s - %s" % (monday.strftime("%d.%m"), saturday.strftime("%d.%m")),
                "date_from": fields.Date.to_string(monday),
                "date_to": fields.Date.to_string(saturday),
                "blocks": blocks,
            })

        return {
            "date_from": fields.Date.to_string(date_from),
            "date_to": fields.Date.to_string(date_to),
            "rooms": room_infos,
            "slots": [self._slot_label(i, day_start_min) for i in range(slot_count)],
            "weeks": weeks,
            "stats": self._board_stats(date_from, date_to, room_ids, domain),
            "min_slot_minutes": FREE_SLOT_MINUTES,
            "filter_options": self._filter_options(),
        }

    @api.model
    def _board_stats(self, date_from, date_to, room_ids, lesson_domain):
        """Mini dashboards above the board, each against the previous period
        of the same length (a week by default) for the up/down arrow."""
        # the date bounds are re-added per period by _period_stats
        base_domain = [
            leaf for leaf in lesson_domain
            if not (isinstance(leaf, (list, tuple)) and leaf[0] == "start_date")
        ]
        span = timedelta(days=(date_to - date_from).days + 1)
        cur = self._period_stats(date_from, date_to, room_ids, base_domain)
        prev = self._period_stats(
            date_from - span, date_to - span, room_ids, base_domain)

        hours = FREE_SLOT_MINUTES / 60.0
        hours_label = ("%.1f" % hours).rstrip("0").rstrip(".").replace(".", ",")
        return [
            {
                "key": "free_rooms",
                "label": "Bo'sh xonalar soni",
                "value": cur["free_rooms"],
                "prev": prev["free_rooms"],
                "delta": cur["free_rooms"] - prev["free_rooms"],
                "hint": "%s xonadan · %s ta bo'sh %s soatlik oyna" % (
                    len(room_ids), cur["free_windows"], hours_label),
            },
            {
                "key": "events",
                "label": "Eventlar soni",
                "value": cur["events"],
                "prev": prev["events"],
                "delta": cur["events"] - prev["events"],
                "hint": "majlis / konsultatsiya / mehmon",
            },
            {
                "key": "groups",
                "label": "Guruhlar soni",
                "value": cur["groups"],
                "prev": prev["groups"],
                "delta": cur["groups"] - prev["groups"],
                "hint": "davrda darsi bor guruhlar",
            },
        ]

    @api.model
    def get_free_slots(self, params=None):
        """"Bo'sh joy topish": free windows grouped by day then room, so a new
        lesson or event can be dropped straight into one."""
        params = params or {}
        today = fields.Date.context_today(self)
        date_from = fields.Date.to_date(params.get("date_from")) or (
            today - timedelta(days=today.weekday())
        )
        date_to = fields.Date.to_date(params.get("date_to")) or (
            date_from + timedelta(days=5)
        )
        if date_to < date_from:
            date_from, date_to = date_to, date_from

        minutes = int(params.get("min_minutes") or FREE_SLOT_MINUTES)
        minutes = max(SLOT_MINUTES, min(minutes, FIXED_END_MIN - FIXED_START_MIN))

        Room = self.env["edu.room"]
        room_id = params.get("room_id") or False
        rooms = Room.browse(int(room_id)) if room_id else Room.search([("active", "=", True)])
        rooms = rooms.sorted(lambda r: (r.sequence or 0, r.id))

        windows = self._free_windows(
            date_from, date_to, rooms.ids, min_minutes=minutes)

        order = {rid: i for i, rid in enumerate(rooms.ids)}
        days = {}
        for w in windows:
            day = days.setdefault(w["date"], {
                "date": w["date"],
                "label": w["day_label"],
                "weekday": w["weekday"],
                "rooms": {},
            })
            room = day["rooms"].setdefault(w["room_id"], {
                "room_id": w["room_id"],
                "room_name": w["room_name"],
                "capacity": w["capacity"],
                "windows": [],
            })
            room["windows"].append({
                "start_min": w["start_min"],
                "end_min": w["end_min"],
                "label": w["label"],
                "fits": w["fits"],
            })

        return {
            "date_from": fields.Date.to_string(date_from),
            "date_to": fields.Date.to_string(date_to),
            "min_minutes": minutes,
            "total": len(windows),
            "days": [
                dict(day, rooms=sorted(
                    day["rooms"].values(),
                    key=lambda r: order.get(r["room_id"], 0),
                ))
                for _d, day in sorted(days.items())
            ],
        }

    @api.model
    def _filter_options(self):
        rooms = self.env["edu.room"].search([("active", "=", True)])
        # same rule as the board query: finished groups are not on the schedule
        groups = self.env["edu.group"].search(
            [("active", "=", True), ("state", "not in", list(CLOSED_GROUP_STATES))],
            order="name",
        )
        teachers = (
            groups.mapped("teacher_id")
            | self.env["edu.timetable"].search([
                ("group_id.active", "=", True),
                ("group_id.state", "not in", list(CLOSED_GROUP_STATES)),
            ]).mapped("teacher_id")
        ).sudo()  # names only; see comment in _group_snapshot
        return {
            "rooms": [{"id": r.id, "name": r.name} for r in rooms.sorted(lambda r: (r.sequence or 0, r.id))],
            "teachers": [{"id": t.id, "name": t.name} for t in teachers.sorted("name")],
            "groups": [{"id": g.id, "name": g.name} for g in groups],
        }

    # ------------------------------------------------------------------
    # card click -> wizard
    # ------------------------------------------------------------------
    @api.model
    def open_lesson_wizard(self, group_id, timetable_ids=None):
        # Booking cards carry key "b<id>" instead of a group id. The new JS
        # routes them elsewhere, but a browser still running pre-1.4.0 assets
        # lands here with 'b1' — open the booking form instead of crashing.
        if isinstance(group_id, str) and group_id.startswith("b"):
            booking = self.env["dars.jadvali.booking"].browse(int(group_id[1:]))
            return {
                "type": "ir.actions.act_window",
                "name": booking.name,
                "res_model": "dars.jadvali.booking",
                "res_id": booking.id,
                "view_mode": "form",
                "views": [(False, "form")],
                "target": "new",
            }
        group = self.env["edu.group"].browse(int(group_id))
        snap = self._group_snapshot(group)
        wizard = self.env["dars.jadvali.lesson.wizard"].create({
            "group_id": group.id,
            "lessons_reja": snap["lessons_reja"],
            "lessons_fakt": snap["lessons_fakt"],
            "probniy": snap["probniy"],
            "student_count": snap["students"],
            "timetable_ids": [(6, 0, timetable_ids or [])],
        })
        return {
            "type": "ir.actions.act_window",
            "name": group.name,
            "res_model": "dars.jadvali.lesson.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            # doAction() from JS bypasses the server-side action loader, so the
            # views list the web client normally derives must be given explicitly.
            "views": [(False, "form")],
            "target": "new",
        }
