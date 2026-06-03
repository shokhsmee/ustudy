from odoo import http, _
from odoo.fields import Domain
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


class CustomerPortalFinance(CustomerPortal):

    def _finance_scope_domain(self, partner):
        """Build a cc.finance domain for `partner` that respects each group
        enrollment's starting module.

        For a mid-joiner (joined a group from the middle of a module), payments
        for modules *before* their starting_module_id must not appear. Records
        with no module snapshot or no student line (general payments) are always
        shown. Mirrors edu.group.student._get_module_scope_domain()."""
        base = [("partner_id", "=", partner.id), ("state", "=", "confirmed")]

        lines = request.env["edu.group.student"].sudo().search([
            ("student_id", "=", partner.id),
        ])

        # General records (not tied to a module or to a group line) are always shown.
        branches = [
            [("student_line_id", "=", False)],
            [("module_id", "=", False)],
        ]
        for line in lines:
            if line.starting_module_id:
                branches.append([
                    ("student_line_id", "=", line.id),
                    ("module_id.sequence", ">=", line.starting_module_id.sequence),
                ])
            else:
                # Joined at the group's start -> no module is hidden.
                branches.append([("student_line_id", "=", line.id)])

        return Domain.AND([base, Domain.OR(branches)])

    def _finance_group_summaries(self, partner):
        """Per-enrollment debt/lesson summary, already scoped from the student's
        enrollment_date / starting module by the computed fields themselves."""
        lines = request.env["edu.group.student"].sudo().search([
            ("student_id", "=", partner.id),
            ("group_id.active", "=", True),
        ])
        summaries = []
        for line in lines:
            debt_amount = max(0.0, line.passed_lessons_amount - line.paid_amount_total)
            summaries.append({
                "group_name": line.group_id.name,
                "course_name": line.group_id.course_id.name,
                "starting_module": line.starting_module_id.name or "",
                "enrollment_date": line.enrollment_date,
                "state": line.state,
                "passed_lessons": line.passed_lessons_count,
                "paid_lessons": line.paid_lessons_count,
                "debt_lessons": int(line.debt_lessons_count),
                "passed_amount": line.passed_lessons_amount,
                "paid_amount": line.paid_amount_total,
                "debt_amount": debt_amount,
            })
        return summaries

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)

        partner = request.env.user.partner_id

        if 'finance_count' in counters:
            values['finance_count'] = request.env['cc.finance'].sudo().search_count(
                self._finance_scope_domain(partner)
            )

        return values

    @http.route(['/my/finance', '/my/finance/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_finance(self, page=1, **kw):

        partner = request.env.user.partner_id
        Finance = request.env['cc.finance'].sudo()

        domain = self._finance_scope_domain(partner)

        total = Finance.search_count(domain)

        pager = portal_pager(
            url="/my/finance",
            total=total,
            page=page,
            step=20
        )

        records = Finance.search(
            domain,
            order="date desc, id desc",
            limit=20,
            offset=pager['offset']
        )

        values = {
            "records": records,
            "group_summaries": self._finance_group_summaries(partner),
            "currency": partner.company_id.currency_id or request.env.company.currency_id,
            "page_name": "finance",
            "pager": pager,
            "default_url": "/my/finance",
        }

        return request.render("edu_finance.portal_my_finance", values)
