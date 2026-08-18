# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

import pytz

from odoo import api, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class EduSalesDashboard(models.AbstractModel):
    """Sotuv KPI dashboard data source.

    Lidlar — amoCRM dan (amocrm.dashboard._fetch_leads: Call-Center + Sotuv
    voronkalari, sozlamalardagi filtr bilan). Sotuvlar/tushum — Sotuvlar
    ilovasidagi tasdiqlangan buyurtmalardan. Konversiya = buyurtmalar / lidlar.
    amoCRM menejerlarini Odoo foydalanuvchisiga amocrm.employee.user_id
    bog'lab turadi.
    """
    _name = "edu.sales.dashboard"
    _description = "Sotuv KPI dashboard"

    @api.model
    def get_sales_kpi_data(self, date_from, date_to):
        if not self.env.user.has_group("ustudy_sales.group_sales_manager"):
            raise AccessError(_("Sotuv KPI dashboard uchun sizda rol yo'q."))
        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d")
            d_to = datetime.strptime(date_to, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise UserError(_("Sana formati noto'g'ri."))
        if d_from > d_to:
            raise UserError(_("Boshlanish sanasi tugash sanasidan keyin bo'lmasin."))

        managers = {}

        def bucket(key, name):
            return managers.setdefault(key, {
                "key": "%s-%s" % key,
                "name": name,
                "leads": 0, "orders": 0,
                "revenue": 0.0, "paid": 0.0,
                "_courses": {},
            })

        # ---------------- Lidlar (amoCRM, filtrlangan voronkalar) --------
        from_ts = int(d_from.timestamp())
        to_ts = int((d_to + timedelta(days=1)).timestamp()) - 1
        leads = self.env["amocrm.dashboard"]._fetch_leads(from_ts, to_ts)

        employees = self.env["amocrm.employee"].sudo().search([])
        amo_to_user = {
            e.amocrm_id: e.user_id.id for e in employees if e.user_id
        }
        amo_names = {e.amocrm_id: e.name for e in employees}

        for lead in leads:
            amo_uid = lead.get("responsible_user_id") or 0
            user_id = amo_to_user.get(amo_uid)
            key = ("u", user_id) if user_id else ("a", amo_uid)
            m = bucket(key, amo_names.get(amo_uid) or ("ID %s" % amo_uid))
            m["leads"] += 1

        # ---------------- Sotuvlar (Odoo buyurtmalari) -------------------
        # date_order is UTC; the period is interpreted in the user's tz.
        tz = pytz.timezone(self.env.user.tz or "Asia/Tashkent")
        start_dt = tz.localize(d_from).astimezone(pytz.utc).replace(tzinfo=None)
        end_dt = tz.localize(d_to + timedelta(days=1)).astimezone(
            pytz.utc).replace(tzinfo=None)

        orders = self.env["edu.sale.order"].search([
            ("state", "=", "confirmed"),
            ("date_order", ">=", start_dt),
            ("date_order", "<", end_dt),
        ])
        for order in orders:
            uid = order.user_id.id or 0
            key = ("u", uid) if uid else ("a", 0)
            m = bucket(key, order.user_id.name or _("Belgilanmagan"))
            if uid:
                m["name"] = order.user_id.name  # Odoo name wins over amoCRM's
            m["orders"] += 1
            m["revenue"] += order.amount_total
            m["paid"] += order.paid_amount
            for line in order.order_line:
                cname = line.product_id.name or "?"
                c = m["_courses"].setdefault(cname, {"count": 0, "amount": 0.0})
                c["count"] += int(line.quantity)
                c["amount"] += line.price_subtotal

        # ---------------- natija -----------------------------------------
        result_managers = []
        for m in managers.values():
            conv = (m["orders"] * 100.0 / m["leads"]) if m["leads"] else 0.0
            courses = [
                {"name": name, "count": c["count"], "amount": c["amount"]}
                for name, c in sorted(
                    m.pop("_courses").items(), key=lambda kv: -kv[1]["amount"]
                )
            ]
            m.update({
                "conversion": round(conv, 2),
                "courses": courses,
            })
            result_managers.append(m)
        result_managers.sort(
            key=lambda m: (-m["revenue"], -m["orders"], -m["leads"]))

        totals = {
            "leads": sum(m["leads"] for m in result_managers),
            "orders": sum(m["orders"] for m in result_managers),
            "revenue": sum(m["revenue"] for m in result_managers),
            "paid": sum(m["paid"] for m in result_managers),
        }
        totals["conversion"] = round(
            totals["orders"] * 100.0 / totals["leads"], 2
        ) if totals["leads"] else 0.0

        return {
            "date_from": date_from,
            "date_to": date_to,
            "managers": result_managers,
            "totals": totals,
        }
