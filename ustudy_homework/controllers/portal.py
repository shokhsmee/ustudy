import json

from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


class CustomerPortalLessons(CustomerPortal):

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()

        partner = request.env.user.partner_id
        LessonReport = request.env["edu.student.lesson.report"].sudo()
        values["lesson_report_count"] = LessonReport.search_count(
            LessonReport.filter_guruhga_qoshilgan(student_id=partner.id)
        )

        return values
    
    @http.route(['/my', '/my/home'], type='http', auth="user", website=True)
    def home(self, **kw):
        response = super().home(**kw)
        return response
    
    
    def _lesson_student_groups(self, partner):
        """Groups the student has lessons in (one entry per group)."""
        LessonReport = request.env["edu.student.lesson.report"].sudo()
        base_domain = LessonReport.filter_guruhga_qoshilgan(student_id=partner.id)
        return LessonReport.search(base_domain).mapped("group_id")

    def _selected_lesson_group(self, partner, group_id):
        """Resolve the chosen group, defaulting to the student's first group.

        A student enrolled in several groups would otherwise see all groups'
        lessons mixed together, so the lessons page always scopes to a single
        group (selectable when there is more than one)."""
        groups = self._lesson_student_groups(partner)
        if group_id:
            try:
                group_id = int(group_id)
            except (TypeError, ValueError):
                group_id = None
            if group_id and group_id in groups.ids:
                return groups.browse(group_id), groups
        return (groups[:1], groups)

    @http.route(['/my/lessons', '/my/lessons/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_lessons(self, page=1, group_id=None, **kw):

        partner = request.env.user.partner_id
        LessonReport = request.env["edu.student.lesson.report"].sudo()

        selected_group, groups = self._selected_lesson_group(partner, group_id)

        domain = LessonReport.filter_guruhga_qoshilgan(student_id=partner.id)
        if selected_group:
            domain = domain + [("group_id", "=", selected_group.id)]

        total = LessonReport.search_count(domain)

        pager = portal_pager(
            url="/my/lessons",
            url_args={"group_id": selected_group.id} if selected_group else {},
            total=total,
            page=page,
            step=20
        )

        records = LessonReport.search(
            domain,
            limit=20,
            offset=pager["offset"]
        )

        values = {
            "records": records,
            "page_name": "lessons",
            "pager": pager,
            "default_url": "/my/lessons",
            "groups": groups,
            "selected_group": selected_group,
        }

        return request.render("ustudy_homework.portal_my_lessons", values)


    @http.route(['/my/lessons/calendar'], type='http', auth="user", website=True)
    def portal_my_lessons_calendar(self, group_id=None, **kw):

        partner = request.env.user.partner_id
        LessonReport = request.env["edu.student.lesson.report"].sudo()

        selected_group, groups = self._selected_lesson_group(partner, group_id)

        domain = LessonReport.filter_guruhga_qoshilgan(student_id=partner.id)
        if selected_group:
            domain = domain + [("group_id", "=", selected_group.id)]

        records = LessonReport.search(domain, order="start_datetime asc, id asc")

        # FullCalendar event colours by lesson state.
        colors = {
            "completed": "#198754",
            "in_progress": "#fd7e14",
            "scheduled": "#0d6efd",
            "cancelled": "#dc3545",
        }
        events = []
        for rec in records:
            if not rec.start_datetime:
                continue
            events.append({
                "title": rec.timetable_name or (rec.slide_id.display_name or "Dars"),
                "start": rec.start_datetime.isoformat(),
                "end": rec.end_datetime.isoformat() if rec.end_datetime else False,
                "color": colors.get(rec.timetable_state, "#6c757d"),
            })

        return request.render("ustudy_homework.portal_my_lessons_calendar", {
            "records": records,
            "events_json": json.dumps(events),
            "page_name": "lessons_calendar",
            "groups": groups,
            "selected_group": selected_group,
        })