from odoo import api, fields, models
from odoo.exceptions import UserError


import logging
_logger = logging.getLogger(__name__)

class SlideSlide(models.Model):
    _inherit = "slide.slide"

    homework_ids = fields.One2many('edu.homework', 'slide_id', string='Homeworks')
    homework_count = fields.Integer(string='Homeworks', compute='_compute_homework_count')

    @api.depends('homework_ids')
    def _compute_homework_count(self):
        for rec in self:
            rec.homework_count = len(rec.homework_ids)

    # ---------- homework auto-create / auto-publish ----------
    @api.model_create_multi
    def create(self, vals_list):
        slides = super().create(vals_list)
        slides._ensure_homework()
        return slides

    def write(self, vals):
        res = super().write(vals)
        # Publishing a slide publishes its homework too. is_published is the
        # stored flag of website.published.mixin; website_published is its
        # related alias — website toggles may write either key.
        if vals.get('is_published') or vals.get('website_published'):
            homeworks = self.env['edu.homework'].sudo().search([
                ('slide_id', 'in', self.ids),
                ('is_published', '=', False),
            ])
            if homeworks:
                homeworks.write({'is_published': True})
        return res

    def _ensure_homework(self):
        """Create one homework per lesson slide that has none yet.

        The homework starts with the slide's publish state: hidden drafts get a
        hidden homework, and publishing the slide later publishes it (write()).
        Sudo: slides may be created by officers without edu.homework rights.
        """
        Homework = self.env['edu.homework'].sudo()
        for slide in self:
            if slide.is_category or slide.homework_ids:
                continue
            Homework.create({
                'name': f"Uyga vazifa: {slide.name}",
                'slide_id': slide.id,
                'channel_id': slide.channel_id.id if slide.channel_id else False,
                'is_published': slide.is_published,
            })

    def lesson_started_for(self, user=None):
        """True if this slide's lesson has been STARTED for the given user.

        "Started" means the user belongs to a group that has a timetable entry
        for this slide whose state is ``in_progress`` or ``completed`` (i.e. the
        teacher pressed "Start lesson" via edu.timetable.action_mark_in_progress).

        Officers/teachers (website_slides officer) always pass, so they can
        manage/preview. Public or non-enrolled users get False.
        """
        self.ensure_one()
        user = user or self.env.user

        # Managers/teachers can always see, for management & preview.
        if user.has_group('website_slides.group_website_slides_officer'):
            return True

        partner = user.partner_id
        if not partner:
            return False

        return bool(self.env['edu.timetable'].sudo().search_count([
            ('slide_id', '=', self.id),
            ('group_id.student_line_ids.student_id', '=', partner.id),
            ('state', 'in', ('in_progress', 'completed')),
        ]))

    def get_visible_homeworks(self, user=None):
        """Published homeworks for this slide, gated by lesson start.

        Returns the published homeworks only if the lesson has been started for
        ``user`` (see :meth:`lesson_started_for`); otherwise an empty recordset.
        """
        self.ensure_one()
        published = self.homework_ids.filtered(lambda h: h.is_published)
        if not published:
            return published
        if not self.lesson_started_for(user):
            return self.env['edu.homework']
        return published

    def get_my_homework_mark(self):
        """Return latest graded mark for this slide for current user (or False)."""
        self.ensure_one()
        user = self.env.user
        if user._is_public():
            return False

        Submission = self.env['edu.homework.submission'].sudo()
        sub = Submission.search([
            ('homework_id.slide_id', '=', self.id),
            ('user_id', '=', user.id),
            ('mark', '!=', False),
        ], order="submit_date desc", limit=1)

        return sub.mark if sub else False
    
    
    def is_locked_for(self, user):
        self.ensure_one()
        return not self.can_access_for(user)
    
    def can_access_for(self, user):
        self.ensure_one()

        # Always allow officers
        if user.has_group('website_slides.group_website_slides_officer'):
            return True

        # Public users: keep accessible (change to False if you want lock for public too)
        if user._is_public():
            return True

        # ALWAYS define prev_slide
        prev_slide = self.env['slide.slide'].sudo().search([
            ('channel_id', '=', self.channel_id.id),
            ('sequence', '<', self.sequence),
            ('website_published', '=', True),
        ], order="sequence desc, id desc", limit=1)

        # First slide
        if not prev_slide:
            return True

        # Homeworks of previous slide
        published_homeworks = self.env['edu.homework'].sudo().search([
            ('slide_id', '=', prev_slide.id),
            ('is_published', '=', True),
        ])

        # STRICT (recommended for “turn by turn”):
        # if previous slide has no homework => lock next slide
        if not published_homeworks:
            return False

        # Must have at least one graded submission for previous slide homeworks
        passed = self.env['edu.homework.submission'].sudo().search_count([
            ('homework_id', 'in', published_homeworks.ids),
            ('user_id', '=', user.id),
            ('state', '=', 'graded'),
        ]) > 0

        return passed
