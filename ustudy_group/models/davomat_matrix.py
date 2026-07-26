from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Attendance matrix (Excel-style replacement of the OCA web_timeline view):
# rows = students, columns = lessons grouped per module, cells = Bor/Yo'q,
# plus per-lesson attendance %, per-module teacher totals and per-student
# per-module summary — replicating the school's Google Sheet layout.

UZ_MONTHS_SHORT = [
    "Yan", "Fev", "Mar", "Apr", "May", "Iyn",
    "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek",
]

STATE_LABELS = {
    "active": "Faol",
    "completed": "Tugatgan",
    "frozen": "Muzlatilgan",
    "cancelled": "Guruhdan chetlatilgan",
}


class DavomatMatrix(models.AbstractModel):
    _name = "edu.davomat.matrix"
    _description = "Guruh davomat matritsasi (jadval ko'rinishi)"

    @api.model
    def _fmt_date(self, d):
        return "%02d %s %s" % (d.day, UZ_MONTHS_SHORT[d.month - 1], d.year) if d else ""

    @api.model
    def _fmt_time(self, float_time):
        minutes = int(round((float_time or 0.0) * 60))
        return "%02d:%02d" % (minutes // 60, minutes % 60)

    @api.model
    def _days_label(self, group):
        """'juft 18:30-20:00'-style suffix built from lesson days + times."""
        seqs = set(group.lesson_days.mapped("sequence"))
        if seqs and seqs <= {2, 4, 6}:
            days = "juft"
        elif seqs and seqs <= {1, 3, 5}:
            days = "toq"
        else:
            days = "/".join(group.lesson_days.sorted("sequence").mapped("name")) or ""
        time_label = ""
        if group.lesson_start or group.lesson_end:
            time_label = "%s-%s" % (
                self._fmt_time(group.lesson_start), self._fmt_time(group.lesson_end),
            )
        return " ".join(p for p in (days, time_label) if p)

    @api.model
    def get_matrix_data(self, group_id):
        group = self.env["edu.group"].browse(int(group_id))
        group.check_access("read")
        config = self.env["edu.config"].get_config()
        lpm = config.lessons_per_module or 12

        lessons = self.env["edu.timetable"].search(
            [("group_id", "=", group.id), ("state", "!=", "cancelled")],
            order="start_datetime asc",
        )

        # last attendance per lesson -> {student_id: status}. Confirmed wins;
        # a DRAFT attendance (lesson started/completed but the end-photo
        # confirmation step was never finished) is used as fallback so the
        # marks still show on the board instead of an empty 0.00% column —
        # those lessons are flagged "unconfirmed" and rendered faded.
        # match by timetable (not group_id): a half-created attendance can be
        # left with NULL stored-related group_id (seen in prod, att 153) and
        # must still land on its lesson's column
        attendances = self.env["edu.attendance"].search(
            [("timetable_id", "in", lessons.ids), ("state", "in", ("draft", "confirmed"))],
            order="id asc",
        )
        status_by_lesson = {}
        confirmed_lessons = set()
        for att in attendances:
            tt_id = att.timetable_id.id
            if att.state == "confirmed":
                confirmed_lessons.add(tt_id)
            elif tt_id in confirmed_lessons:
                continue  # stray draft next to an already confirmed one
            status_by_lesson[tt_id] = {
                line.student_id.id: line.status for line in att.attendance_line_ids
            }
        draft_only_lessons = set(status_by_lesson) - confirmed_lessons

        start_no = max(group.start_lesson_number or 1, 1)
        modules = []  # ordered; one entry per module sequence
        by_seq = {}
        lesson_infos = {}
        for idx, tt in enumerate(lessons):
            no = start_no + idx
            seq = (no - 1) // lpm + 1
            pos = (no - 1) % lpm + 1
            local = fields.Datetime.context_timestamp(tt, tt.start_datetime)
            held = tt.state in ("in_progress", "completed")
            info = {
                "id": tt.id,
                "no": no,
                "pos_label": "%d - Dars" % pos,
                "date": self._fmt_date(local.date()),
                "raw_date": local.date(),
                "teacher": tt.teacher_id.sudo().name or "",
                "held": held,
                # started (or even completed) but the davomat was never
                # confirmed — shown faded with a warning on the board
                "unconfirmed": tt.id in draft_only_lessons,
                "present": 0,
                "absent": 0,
            }
            lesson_infos[tt.id] = info
            if seq not in by_seq:
                by_seq[seq] = {"seq": seq, "label": "%d-Modul Davomat" % seq, "lessons": []}
                modules.append(by_seq[seq])
            by_seq[seq]["lessons"].append(info)

        # ---- today's lesson: drives the in-board teacher flow (Darsni
        # boshlash → davomat selectorlari → Darsni yakunlash), mirroring the
        # timetable form. Only the day's own lesson is actionable. ----
        today = fields.Date.context_today(self)
        today_tt = lessons.filtered(lambda t: t.start_date == today)[:1]
        today_status_by_student = {}
        today_block = {"has_lesson": False, "lesson_id": False}
        if today_tt:
            today_att = self.env["edu.attendance"].search(
                [("timetable_id", "=", today_tt.id)], order="id desc", limit=1,
            )
            if today_att:
                today_status_by_student = {
                    line.student_id.id: line.status
                    for line in today_att.attendance_line_ids
                }
            info = lesson_infos.get(today_tt.id, {})
            today_block = {
                "has_lesson": True,
                "lesson_id": today_tt.id,
                "lesson_no": info.get("no"),
                "date": info.get("date"),
                "state": today_tt.state,
                "attendance_id": today_att.id if today_att else False,
                "attendance_state": today_att.state if today_att else False,
                # start only when no attendance exists yet and the lesson is not
                # already completed; otherwise it is either in progress or done.
                "can_start": not today_att and today_tt.state != "completed",
                "in_progress": bool(today_att and today_att.state == "draft"),
                "done": bool(today_att and today_att.state == "confirmed"),
                "module_seq": (info.get("no", 1) - 1) // lpm + 1,
                "has_slide": bool(today_tt.slide_id),
            }
            # a lesson running right now is legitimately draft — no warning
            if today_block["in_progress"] and info:
                info["unconfirmed"] = False

        # students: enrollment order. Only active enrollments appear on the
        # attendance sheet — students removed from the group (cancelled /
        # Guruhdan chetlatilgan) are excluded entirely.
        # Dedupe by student (old data may hold duplicate enrollment lines for
        # one student — same guard as the lesson-report SQL view's DISTINCT ON):
        # keep the earliest-enrolled line.
        students = []
        seen_students = set()
        lines = group.student_line_ids.sorted(
            key=lambda l: (l.enrollment_date or fields.Date.from_string("1900-01-01"), l.id)
        )
        for line in lines:
            if line.state == "cancelled":
                continue
            if line.student_id.id in seen_students:
                continue
            seen_students.add(line.student_id.id)
            removed_date = None
            cells = {}
            summary = {m["seq"]: {"present": 0, "absent": 0} for m in modules}
            for tt in lessons:
                info = lesson_infos[tt.id]
                marked = status_by_lesson.get(tt.id, {}).get(line.student_id.id)
                if marked in ("present", "absent"):
                    cells[str(tt.id)] = marked
                    info[marked] += 1
                    seq = (info["no"] - 1) // lpm + 1
                    summary[seq][marked] += 1
                elif line.enrollment_date and info["raw_date"] < line.enrollment_date:
                    cells[str(tt.id)] = "na"       # joined later
                elif removed_date and info["raw_date"] > removed_date:
                    cells[str(tt.id)] = "na"       # left the group
                else:
                    cells[str(tt.id)] = ""
            students.append({
                "line_id": line.id,
                "student_id": line.student_id.id,
                "name": line.student_id.name,
                "state": line.state,
                "state_label": STATE_LABELS.get(line.state, line.state or ""),
                "removed_date": self._fmt_date(removed_date),
                # default for today's editable selector (all present on start)
                "today_status": today_status_by_student.get(line.student_id.id, "present"),
                "cells": cells,
                "summary": {
                    str(seq): "Bor %d, Yo'q %d, Sababli 0" % (v["present"], v["absent"])
                    for seq, v in summary.items()
                },
            })

        # per-lesson percentage + per-module teacher totals / module %
        for module in modules:
            teacher_counts = {}
            m_present = m_marked = 0
            for info in module["lessons"]:
                marked = info["present"] + info["absent"]
                info["pct"] = (
                    "%.2f%%" % (info["present"] * 100.0 / marked) if marked else "0.00%"
                )
                m_present += info["present"]
                m_marked += marked
                if info["held"]:
                    teacher_counts[info["teacher"]] = teacher_counts.get(info["teacher"], 0) + 1
                info.pop("raw_date", None)
            module["pct"] = (
                "%.2f%%" % (m_present * 100.0 / m_marked) if m_marked else "0.00%"
            )
            module["teacher_totals"] = [
                {"name": name or "—", "count": count}
                for name, count in sorted(teacher_counts.items(), key=lambda kv: -kv[1])
            ]

        # module to open on: the one holding the last held lesson
        current_seq = modules[0]["seq"] if modules else 1
        for module in modules:
            if any(info["held"] for info in module["lessons"]):
                current_seq = module["seq"]
        # when there is a lesson today, open its module so the teacher lands on
        # the editable column straight away
        if today_block.get("has_lesson"):
            current_seq = today_block["module_seq"]

        return {
            "group": {
                "id": group.id,
                "name": group.name,
                "label": "%s (%s)" % (group.name, self._days_label(group)),
                "start_date": self._fmt_date(group.start_date),
                "student_count": len(students),
            },
            # KPI cards (same numbers as the group form's mini dashboard)
            "kpi": {
                "active_students": group.active_student_count,
                "attendance": group.attendance_display,
                "homework": group.homework_display,
                "debt_total": group.debt_total_display,
                "stopped_students": group.stopped_student_count,
            },
            "current_seq": current_seq,
            "today": today_block,
            "modules": modules,
            "students": students,
        }

    # ------------------------------------------------------------------
    # In-board lesson flow (mirrors the timetable form's teacher flow)
    # ------------------------------------------------------------------
    @api.model
    def _today_lesson(self, group):
        """The group's own lesson scheduled for today (if any)."""
        today = fields.Date.context_today(self)
        return self.env["edu.timetable"].search([
            ("group_id", "=", group.id),
            ("state", "!=", "cancelled"),
            ("start_date", "=", today),
        ], order="start_datetime asc", limit=1)

    @api.model
    def matrix_start_lesson(self, group_id):
        """Open the start-photo camera wizard for today's lesson.

        Reuses edu.timetable.action_start_attendance (same slide/duplicate
        guards) and tags the flow with matrix_flow so the wizard just closes
        back to the board instead of navigating to the attendance form."""
        group = self.env["edu.group"].browse(int(group_id))
        group.check_access("read")
        tt = self._today_lesson(group)
        if not tt:
            raise UserError(_("Bugun uchun dars jadvali topilmadi."))
        if tt.attendance_ids:
            raise UserError(_("Bu dars uchun davomat allaqachon boshlangan."))
        action = tt.action_start_attendance()
        action.setdefault("context", {})
        action["context"]["matrix_flow"] = True
        # doAction() is called client-side with this raw dict, so it needs an
        # explicit views list (the server only injects one when an action is
        # executed, not when a method returns a plain dict).
        action.setdefault("views", [[False, "form"]])
        return action

    @api.model
    def matrix_set_status(self, attendance_id, student_id, status):
        """Set one student's present/absent on the draft attendance (live)."""
        if status not in ("present", "absent"):
            raise UserError(_("Noto'g'ri davomat holati."))
        att = self.env["edu.attendance"].browse(int(attendance_id))
        if not att.exists():
            raise UserError(_("Davomat topilmadi."))
        if att.state != "draft":
            raise UserError(_("Tasdiqlangan davomatni o'zgartirib bo'lmaydi."))
        line = att.attendance_line_ids.filtered(
            lambda l: l.student_id.id == int(student_id))[:1]
        if line:
            line.write({"status": status})
        else:
            self.env["edu.attendance.line"].create({
                "attendance_id": att.id,
                "student_id": int(student_id),
                "status": status,
            })
        return True

    @api.model
    def matrix_finish_lesson(self, group_id):
        """Open the Darsni yakunlash (homework) wizard for today's lesson.

        matrix_flow chains it: homework wizard → end-photo camera wizard →
        attendance confirmed (lesson counts advance + teacher salary snapshot
        via ustudy_teacher_salary)."""
        group = self.env["edu.group"].browse(int(group_id))
        group.check_access("read")
        tt = self._today_lesson(group)
        if not tt:
            raise UserError(_("Bugun uchun dars jadvali topilmadi."))
        att = self.env["edu.attendance"].search(
            [("timetable_id", "=", tt.id), ("state", "=", "draft")],
            order="id desc", limit=1)
        if not att:
            raise UserError(_("Avval darsni boshlang."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Darsni yakunlash"),
            "res_model": "edu.lesson.complete.wizard",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {
                "default_timetable_id": tt.id,
                "matrix_flow": True,
                "matrix_attendance_id": att.id,
            },
        }
