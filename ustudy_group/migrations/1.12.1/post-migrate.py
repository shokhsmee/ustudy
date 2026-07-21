from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Rename the edu.group.student 'cancelled' status label to
    'Guruhdan chetlatilgan' across every installed language.

    The label was renamed from 'Cancelled' in the Python source, but the DB
    kept a stale translation ('Bekor qilingan' — inherited from the base
    uz_UZ translation of 'Cancelled') on the selection value. Changing the
    Python source only refreshes en_US, so the old uz_UZ value kept winning.
    Overwrite the stored label in all active languages so the new wording
    shows everywhere.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    selection = env["ir.model.fields.selection"].search([
        ("field_id.model", "=", "edu.group.student"),
        ("field_id.name", "=", "state"),
        ("value", "=", "cancelled"),
    ])
    if not selection:
        return
    langs = set(env["res.lang"].search([("active", "=", True)]).mapped("code"))
    langs.add("en_US")
    for lang in langs:
        selection.with_context(lang=lang).write({"name": "Guruhdan chetlatilgan"})
