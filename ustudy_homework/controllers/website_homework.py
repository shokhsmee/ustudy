# -*- coding: utf-8 -*-
import base64
import json

from odoo import http
from odoo.http import request


class WebsiteEduHomework(http.Controller):

    @http.route(['/homework/<int:homework_id>'], type='http', auth='public', website=True)
    def homework_page(self, homework_id, **kw):
        hw = request.env['edu.homework'].sudo().browse(homework_id)
        if not hw.exists() or not hw.is_published:
            return request.not_found()

        # Gate by lesson start: hide content until the student's group has
        # started the lesson this homework belongs to.
        locked = not hw.is_visible_for(request.env.user)

        values = {
            'homework': hw,
            'slide': hw.slide_id.sudo() if hw.slide_id else False,
            'locked': locked,
        }
        return request.render('ustudy_homework.homework_page_template', values)

    # ✅ FIXED: type='http' so normal GET works (no 415)
    @http.route(
        ['/homework/slide/<int:slide_id>/json'],
        type='http',
        auth='public',
        website=True,
        csrf=False,
        sitemap=False,
    )
    def slide_homeworks_json(self, slide_id, **kw):
        # Only expose this slide's homework once the lesson has been started
        # for the requesting user's group.
        slide = request.env['slide.slide'].sudo().browse(slide_id)
        if not slide.exists() or not slide.lesson_started_for(request.env.user):
            hw_objs = request.env['edu.homework']
        else:
            hw_objs = request.env['edu.homework'].sudo().search([
                ('slide_id', '=', slide_id),
                ('is_published', '=', True),
            ], order='due_date asc')

        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        result = [{
            'id': hw.id,
            'name': hw.name,
            'due_date': hw.due_date.isoformat() if hw.due_date else False,
            'url': f"{base_url}/homework/{hw.id}",
        } for hw in hw_objs]

        return request.make_response(
            json.dumps(result),
            headers=[
                ('Content-Type', 'application/json; charset=utf-8'),
                ('Cache-Control', 'no-store'),
            ],
        )

    @http.route(
        ['/homework/<int:homework_id>/submit'],
        type='http',
        auth='user',
        website=True,
        methods=['POST'],
        csrf=True,
    )
    def homework_submit(self, homework_id, **post):
        hw = request.env['edu.homework'].sudo().browse(homework_id)
        if not hw.exists() or not hw.is_published:
            return request.not_found()

        user = request.env.user
        student = user.partner_id

        submission = request.env['edu.homework.submission'].sudo().create({
            'homework_id': hw.id,
            'student_id': student.id,
            'user_id': user.id,
            'comment': post.get('comment') or '',
        })

        files = request.httprequest.files.getlist('attachments')
        for f in files:
            if not f.filename:
                continue
            data = f.read()
            att = request.env['ir.attachment'].sudo().create({
                'name': f.filename,
                'datas': base64.b64encode(data),
                'res_model': 'edu.homework.submission',
                'res_id': submission.id,
                'mimetype': f.content_type,
            })
            submission.attachment_ids = [(4, att.id)]

        return request.redirect(f"/homework/{hw.id}")
