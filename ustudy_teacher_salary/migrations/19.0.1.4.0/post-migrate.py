import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Switch teacher salary to a cash basis: expense is booked at payout, not
    per lesson.

    Previously every confirmed lesson auto-posted a Chiqim (cc.finance expense)
    for the amount EARNED. Those are accruals, not real payments — under the new
    model Chiqimlar must reflect only money actually paid out. So cancel every
    auto-posted earning expense (identified by its link to a 'kirim' salary
    line) and unlink it. The salary ledger's kirim lines stay untouched, so each
    teacher's earned balance (now shown as 'Qolgan qarz') is preserved and can
    be settled properly via the new 'Oylik berish' wizard.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["edu.teacher.salary.line"].search([
        ("cc_finance_id", "!=", False),
        ("transaction_type", "=", "kirim"),
    ])
    cancelled = 0
    for line in lines:
        finance = line.cc_finance_id
        if finance and finance.state != "cancelled":
            finance.with_user(SUPERUSER_ID).write({"state": "cancelled"})
            cancelled += 1
        line.cc_finance_id = False
    _logger.info(
        "ustudy_teacher_salary 1.4.0: cancelled %s auto-posted earning "
        "expense(s); earnings kept as owed balances.", cancelled,
    )
