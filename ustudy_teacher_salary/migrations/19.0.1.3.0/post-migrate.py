from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Switch the teacher-salary basis to 'enrolled'.

    Ustoz oyligi must be calculated for ALL active students shown on the
    attendance sheet — present ('keldi') and absent ('kelmadi') alike — not
    only those marked present. The 'enrolled' basis does exactly that, so we
    move the stored config parameter over from the old 'present' default.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["ir.config_parameter"].set_param(
        "ustudy_teacher_salary.active_basis", "enrolled"
    )
