"""Backfill attempt numbering and the new 'resubmitted' state.

1.8.0 makes a retry a first-class thing: every submission carries its ordinal
(``attempt_no``) and a submission that arrives while an earlier attempt already
exists is stored as ``resubmitted`` instead of ``submitted``. Both are set in
create(), so historical rows need one pass:

* attempt_no  -> row_number() per (homework, student), oldest attempt first;
* state       -> ungraded 2nd+ attempts become 'resubmitted' so the rosters
                 flag them exactly like new ones. Graded/failed attempts keep
                 their verdict — only the "waiting for a ball" rows change.
"""


def migrate(cr, version):
    cr.execute("""
        WITH numbered AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY homework_id, student_id
                       ORDER BY submit_date ASC NULLS FIRST, id ASC
                   ) AS rn
            FROM edu_homework_submission
        )
        UPDATE edu_homework_submission s
           SET attempt_no = numbered.rn
          FROM numbered
         WHERE numbered.id = s.id
           AND s.attempt_no IS DISTINCT FROM numbered.rn
    """)
    cr.execute("""
        UPDATE edu_homework_submission
           SET state = 'resubmitted'
         WHERE state = 'submitted'
           AND attempt_no > 1
    """)
