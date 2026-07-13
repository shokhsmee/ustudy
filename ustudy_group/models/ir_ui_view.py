from odoo import fields, models

# Custom OWL view type: room occupancy / scheduling grid for edu.timetable.
ROOM_BANDLIK_VIEW = ("room_bandlik", "Room Bandlik")


class IrUIView(models.Model):
    _inherit = "ir.ui.view"

    type = fields.Selection(selection_add=[ROOM_BANDLIK_VIEW])

    def _is_qweb_based_view(self, view_type):
        # The arch is a thin declaration (date fields + a few <field>s) consumed
        # by our JS ArchParser, so skip the standard field-based validation.
        return view_type == ROOM_BANDLIK_VIEW[0] or super()._is_qweb_based_view(
            view_type
        )

    def _get_view_info(self):
        return {
            "room_bandlik": {"icon": "fa fa-th", "display_name": "Xonalar bandligi"}
        } | super()._get_view_info()


class ActWindowView(models.Model):
    _inherit = "ir.actions.act_window.view"

    view_mode = fields.Selection(
        selection_add=[ROOM_BANDLIK_VIEW],
        ondelete={"room_bandlik": "cascade"},
    )
