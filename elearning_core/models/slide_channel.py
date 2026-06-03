from odoo import _, models
from odoo.exceptions import UserError


class SlideChannel(models.Model):
    _inherit = "slide.channel"

    def action_publish_all_slides(self):
        self.ensure_one()
        if not self.can_publish:
            raise UserError(_("Sizda ushbu kursdagi darslarni nashr qilish huquqi yo'q."))

        slides_to_publish = self.slide_ids.filtered(
            lambda s: not s.is_category and not s.is_published
        )
        if not slides_to_publish:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Ma'lumot"),
                    "message": _("Nashr qilinmagan darslar topilmadi."),
                    "type": "info",
                    "sticky": False,
                },
            }

        slides_to_publish.write({"is_published": True})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bajarildi"),
                "message": _("%s ta dars nashr qilindi.") % len(slides_to_publish),
                "type": "success",
                "sticky": False,
            },
        }
