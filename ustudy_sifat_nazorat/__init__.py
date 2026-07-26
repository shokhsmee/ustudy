# -*- coding: utf-8 -*-
from . import models


def post_init_backfill(env):
    """Create Sifat Nazorat records for absences that existed before this
    module was installed, so the report is complete from day one."""
    lines = env["edu.attendance.line"].search([("status", "=", "absent")])
    lines._sync_sifat_nazorat()
