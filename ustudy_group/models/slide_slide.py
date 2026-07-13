from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SlideSlide(models.Model):
    _inherit = "slide.slide"

    lesson_no = fields.Integer(
        string="Lesson No.",
        copy=False,
        index=True,
        help="Ketma-ket dars raqami (kurs ichida). Yangi dars kiritilganda "
             "1 dan boshlab avtomatik beriladi va qo'lda o'zgartirilishi mumkin. "
             "Bitta kurs ichida takrorlanmasligi kerak. Dars jadvalidagi 'No.' "
             "shu raqamga qarab tegishli darsni biriktiradi. Modul/bo'lim "
             "sarlavhalariga raqam berilmaydi.",
    )

    # ---------- helpers ----------
    @api.model
    def _next_lesson_no(self, channel):
        """Next free lesson number for a channel (max existing + 1)."""
        if not channel:
            return 1
        # lesson_no != False also excludes NULLs: without it, "lesson_no desc"
        # puts NULL rows first (Postgres DESC default) and an unnumbered slide
        # in the channel would make this return 1, colliding with existing
        # numbers and blocking slide creation via the unique constraint.
        last = self.search(
            [
                ("channel_id", "=", channel.id),
                ("is_category", "=", False),
                ("lesson_no", "!=", False),
            ],
            order="lesson_no desc",
            limit=1,
        )
        return (last.lesson_no or 0) + 1

    def _assign_missing_lesson_no(self):
        """Auto-fill lesson_no for non-category slides that don't have one yet,
        numbering sequentially per channel."""
        by_channel = {}
        for slide in self:
            if slide.is_category or slide.lesson_no or not slide.channel_id:
                continue
            by_channel.setdefault(slide.channel_id, self.browse())
            by_channel[slide.channel_id] |= slide

        for channel, slides in by_channel.items():
            next_no = self._next_lesson_no(channel)
            for slide in slides:
                slide.lesson_no = next_no
                next_no += 1

    # ---------- create ----------
    @api.model_create_multi
    def create(self, vals_list):
        slides = super().create(vals_list)
        slides._assign_missing_lesson_no()
        return slides

    # ---------- constraints ----------
    @api.constrains("lesson_no", "channel_id", "is_category")
    def _check_lesson_no_unique(self):
        for slide in self:
            if slide.is_category or not slide.lesson_no or not slide.channel_id:
                continue
            duplicate = self.search_count(
                [
                    ("id", "!=", slide.id),
                    ("channel_id", "=", slide.channel_id.id),
                    ("is_category", "=", False),
                    ("lesson_no", "=", slide.lesson_no),
                ]
            )
            if duplicate:
                raise ValidationError(
                    _(
                        "Dars raqami %(no)s ushbu kursda allaqachon mavjud. "
                        "Har bir dars raqami kurs ichida takrorlanmasligi kerak.",
                        no=slide.lesson_no,
                    )
                )
