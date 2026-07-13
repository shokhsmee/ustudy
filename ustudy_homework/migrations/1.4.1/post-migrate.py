"""Recompute the stored edu.timetable.homework_id.

Until 1.4.1 ``_compute_homework_id`` fell back to matching ANY published
homework in the lesson's course channel when the lesson had no slide. That
left stale homework links (and stray submission counts) on slide-less lessons.
The compute is now slide-only, but homework_id is a STORED field, so existing
rows keep their old value until explicitly recomputed. This corrects them:
lessons with no slide -> homework_id NULL; lessons with a slide -> the homework
tied to that exact slide (or NULL if the slide has none).
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    timetables = env["edu.timetable"].search([])
    if not timetables:
        return
    timetables._compute_homework_id()
    env.flush_all()
