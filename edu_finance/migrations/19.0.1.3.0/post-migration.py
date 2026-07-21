# -*- coding: utf-8 -*-
def migrate(cr, version):
    """One-time backfill of cc.payment.type.direction.

    Odoo fills a newly-added required field with its default ('kirim') for all
    existing rows, so we cannot rely on IS NULL. This runs once on the 1.3.0
    bump and classifies by category: teacher/employee payouts = chiqim,
    student payments = kirim. 'other' keeps the default (kirim)."""
    cr.execute("""
        UPDATE cc_payment_type
        SET direction = 'chiqim'
        WHERE type_category IN ('teacher', 'employee')
    """)
    cr.execute("""
        UPDATE cc_payment_type
        SET direction = 'kirim'
        WHERE type_category = 'student'
    """)
