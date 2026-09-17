"""Backfill edu_timetable.auto_cancelled_on_done for groups finished BEFORE 1.15.0.

1.15.0 made "Tugallandi" flag the lessons it cancels so that reopening the group
restores exactly those. Groups closed before that upgrade have no flag at all, so
reopening them left an empty schedule (the whole reason SMM U3 ended up with 24
cancelled lessons and no live ones) and needed a manual "Generate Timetable".

Which cancelled rows were "cancelled because the course ended"? The ones after the
group's last HELD lesson (in_progress/completed) — the not-yet-held tail. Rows
cancelled between held lessons are manual cancellations (holidays, moved days) and
must stay cancelled, so they are deliberately left unflagged. A group that never
held a lesson has its whole cancelled schedule flagged.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Odoo skips writing a column default that is falsy, so every pre-existing
    # row got NULL instead of False. Normalize first: a NULL boolean has bitten
    # this codebase before (the group_active copy).
    cr.execute("""
        UPDATE edu_timetable SET auto_cancelled_on_done = FALSE
         WHERE auto_cancelled_on_done IS NULL
    """)
    _logger.info("auto_cancelled_on_done: %s NULL rows normalized to FALSE", cr.rowcount)

    cr.execute("""
        WITH last_held AS (
            SELECT group_id, MAX(start_datetime) AS held_until
              FROM edu_timetable
             WHERE state IN ('in_progress', 'completed')
             GROUP BY group_id
        )
        UPDATE edu_timetable t
           SET auto_cancelled_on_done = TRUE
          FROM edu_group g
     LEFT JOIN last_held h ON h.group_id = g.id
         WHERE t.group_id = g.id
           AND g.state IN ('done', 'cancelled')
           AND t.state = 'cancelled'
           AND (h.held_until IS NULL OR t.start_datetime > h.held_until)
    """)
    flagged = cr.rowcount

    cr.execute("""
        SELECT g.name, count(*)
          FROM edu_timetable t JOIN edu_group g ON g.id = t.group_id
         WHERE t.auto_cancelled_on_done
         GROUP BY g.name ORDER BY g.name
    """)
    per_group = ", ".join("%s: %s" % row for row in cr.fetchall())
    _logger.info(
        "auto_cancelled_on_done: flagged %s lessons of already-finished groups "
        "so reopening restores them (%s)", flagged, per_group or "none")
