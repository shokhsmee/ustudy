from datetime import timedelta
from math import ceil

from odoo import api, fields, models

# 30-minute board grid from 08:00 to 20:00. A lesson card sits on the row that
# contains its local start time and spans (rowspan) every 30-min row up to its
# end time, so a 10:30-12:00 lesson renders exactly over 10:30-12:00.
DAY_START_MIN = 8 * 60
DAY_END_MIN = 20 * 60
SLOT_MINUTES = 30
SLOT_COUNT = (DAY_END_MIN - DAY_START_MIN) // SLOT_MINUTES

# Mon/Wed/Fri = toq (odd) block, Tue/Thu/Sat = juft (even) block. Sunday is
# not part of the board.
PARITY_BY_WEEKDAY = {0: "toq", 2: "toq", 4: "toq", 1: "juft", 3: "juft", 5: "juft"}
PARITY_LABELS = {"toq": "Dush / Chor / Jum", "juft": "Sesh / Pay / Shan"}

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
    def _slot_label(self, idx):
        start = DAY_START_MIN + idx * SLOT_MINUTES
        end = start + SLOT_MINUTES
        return "%02d:%02d - %02d:%02d" % (start // 60, start % 60, end // 60, end % 60)

    @api.model
    def _slot_index(self, local_dt):
        minutes = local_dt.hour * 60 + local_dt.minute
        if DAY_START_MIN <= minutes < DAY_END_MIN:
            return (minutes - DAY_START_MIN) // SLOT_MINUTES
        return None

    @api.model
    def _slot_span(self, s_idx, start_local, end_local):
        """How many 30-min rows the lesson covers from its start row (>= 1)."""
        if not end_local or end_local <= start_local:
            return 1
        end_min = end_local.hour * 60 + end_local.minute
        if end_local.date() != start_local.date():
            end_min = DAY_END_MIN
        end_idx = ceil((min(end_min, DAY_END_MIN) - DAY_START_MIN) / SLOT_MINUTES)
        return max(1, min(end_idx, SLOT_COUNT) - s_idx)

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
            # card title in "Kurs - Guruh" format, e.g. "Graphic Design 12 Oy - U14"
            "course": (
                f"{group.course_id.name} - {group.name}"
                if group.course_id and group.course_id.name != group.name
                else group.name
            ),
            "teacher": group.teacher_id.sudo().name or "",
            "lessons_reja": reja,
            "lessons_fakt": fakt,
            "probniy": probniy,
            "students": students,
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

        # ---- bucket entries: (week_monday, parity, slot_idx, room) -> groups
        snapshots = {}  # group_id -> snapshot (computed once)
        buckets = {}    # (week, parity, slot, room) -> {group_id: {...}}
        week_keys = set()

        for entry in entries:
            local = fields.Datetime.context_timestamp(entry, entry.start_datetime)
            p = PARITY_BY_WEEKDAY.get(local.weekday())
            if not p or (parity and p != parity):
                continue
            s_idx = self._slot_index(local)
            if s_idx is None:
                continue
            local_end = (
                fields.Datetime.context_timestamp(entry, entry.end_datetime)
                if entry.end_datetime
                else None
            )
            span = self._slot_span(s_idx, local, local_end)
            if slot is not False:
                # time filter: keep lessons covering the picked half-hour and
                # render them on that single row (no rowspan to clip).
                if not (s_idx <= slot < s_idx + span):
                    continue
                s_idx, span = slot, 1
            if entry.room_id.id not in room_ids:
                continue

            monday = local.date() - timedelta(days=local.weekday())
            week_keys.add(monday)
            key = (monday, p, s_idx, entry.room_id.id)
            cell = buckets.setdefault(key, {})
            gid = entry.group_id.id
            if gid not in snapshots:
                snapshots[gid] = self._group_snapshot(entry.group_id)
            card = cell.setdefault(
                gid,
                dict(
                    snapshots[gid],
                    capacity=entry.room_id.capacity,
                    room_id=entry.room_id.id,
                    span=1,
                    timetable_ids=[],
                    dates=[],
                ),
            )
            card["span"] = max(card["span"], span)
            card["timetable_ids"].append(entry.id)
            card["dates"].append(local.strftime("%d.%m %H:%M"))

        # ---- assemble weeks -> blocks -> slot rows
        parities = [parity] if parity else ["toq", "juft"]
        slot_indexes = [slot] if slot is not False else list(range(SLOT_COUNT))

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
                    rows.append({"slot": self._slot_label(s_idx), "cells": cells})

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
            "slots": [self._slot_label(i) for i in range(SLOT_COUNT)],
            "weeks": weeks,
            "filter_options": self._filter_options(),
        }

    @api.model
    def _filter_options(self):
        rooms = self.env["edu.room"].search([("active", "=", True)])
        groups = self.env["edu.group"].search([("active", "=", True)], order="name")
        teachers = (
            groups.mapped("teacher_id")
            | self.env["edu.timetable"].search(
                [("group_id.active", "=", True)]
            ).mapped("teacher_id")
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
