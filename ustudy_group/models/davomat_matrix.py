from odoo import api, fields, models

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

        # last confirmed attendance per lesson -> {student_id: status}
        attendances = self.env["edu.attendance"].search(
            [("group_id", "=", group.id), ("state", "=", "confirmed")],
            order="id asc",
        )
        status_by_lesson = {}
        for att in attendances:
            status_by_lesson[att.timetable_id.id] = {
                line.student_id.id: line.status for line in att.attendance_line_ids
            }

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
                "present": 0,
                "absent": 0,
            }
            lesson_infos[tt.id] = info
            if seq not in by_seq:
                by_seq[seq] = {"seq": seq, "label": "%d-Modul Davomat" % seq, "lessons": []}
                modules.append(by_seq[seq])
            by_seq[seq]["lessons"].append(info)

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
            "modules": modules,
            "students": students,
        }
