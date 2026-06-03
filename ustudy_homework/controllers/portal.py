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
    
    
    @http.route(['/my/lessons', '/my/lessons/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_lessons(self, page=1, **kw):

        partner = request.env.user.partner_id
        LessonReport = request.env["edu.student.lesson.report"].sudo()

        domain = LessonReport.filter_guruhga_qoshilgan(student_id=partner.id)

        total = LessonReport.search_count(domain)

        pager = portal_pager(
            url="/my/lessons",
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
        }

        return request.render("ustudy_homework.portal_my_lessons", values)
    
    
    @http.route(['/my/lessons/calendar'], type='http', auth="user", website=True)
    def portal_my_lessons_calendar(self, **kw):

        partner = request.env.user.partner_id
        LessonReport = request.env["edu.student.lesson.report"].sudo()

        records = LessonReport.search(
            LessonReport.filter_guruhga_qoshilgan(student_id=partner.id),
            order="start_datetime asc, id asc"
        )

        return request.render("ustudy_homework.portal_my_lessons_calendar", {
            "records": records,
            "page_name": "lessons_calendar",
        })