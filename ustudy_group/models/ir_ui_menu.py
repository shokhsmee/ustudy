from odoo import api, models

# Apps hidden from plain teachers. Access rights are untouched — the records
# stay reachable via links/actions; only the menu entries disappear.
TEACHER_HIDDEN_MENU_XMLIDS = [
    "contacts.menu_contacts",
    "ustudy_notebook_mgmt.edu_notebook_root",
]


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def _visible_menu_ids(self, debug=False):
        visible_ids = super()._visible_menu_ids(debug=debug)
        user = self.env.user
        if (
            user.has_group("ustudy_group.group_teacher")
            and not user.has_group("ustudy_group.group_edu_admin")
            and not user.has_group("base.group_system")
        ):
            imd = self.env["ir.model.data"]
            hidden_ids = set()
            for xmlid in TEACHER_HIDDEN_MENU_XMLIDS:
                menu_id = imd._xmlid_to_res_id(xmlid, raise_if_not_found=False)
                if menu_id:
                    hidden_ids.update(
                        self.sudo().search([("id", "child_of", menu_id)]).ids
                    )
            if hidden_ids:
                visible_ids = frozenset(visible_ids - hidden_ids)
        return visible_ids
