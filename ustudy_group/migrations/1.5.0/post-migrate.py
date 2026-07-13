"""Backfill lesson_no for existing slides.

For every course channel, number its non-category slides sequentially by their
current display order (sequence, id). Idempotent: only fills slides that do not
already have a number, and never reuses a number already taken in that channel.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Slide = env["slide.slide"]

    channels = Slide.search([("is_category", "=", False)]).mapped("channel_id")
    for channel in channels:
        slides = Slide.search(
            [
                ("channel_id", "=", channel.id),
                ("is_category", "=", False),
            ],
            order="sequence asc, id asc",
        )
        used = {s.lesson_no for s in slides if s.lesson_no}
        next_no = 1
        for slide in slides:
            if slide.lesson_no:
                continue
            while next_no in used:
                next_no += 1
            slide.lesson_no = next_no
            used.add(next_no)
            next_no += 1
