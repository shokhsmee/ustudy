# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

from odoo import api, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

WON_STATUS = 142   # amoCRM system id: "Успешно реализовано" (per-pipeline label varies)
LOST_STATUS = 143  # amoCRM system id: "Закрыто и не реализовано"
COURSE_FIELD_NAME = "Asosiy kursi"  # lead custom field (Important tab)
MAX_PAGES = 200  # 200 × 250 = 50k leads per load, hard stop


class AmocrmDashboard(models.AbstractModel):
    """KPI dashboard data source: leads per manager → conversion, revenue,
    per-stage funnel and the KPI %/bonus from the motivation sheet.

    Sheet structure (see KPI matrix): base = 90 mln revenue + 7% conversion
    → 12% KPI; every 10 mln less → −0.5%; every 1% conversion less → −1%.
    Bonus (Jami summa) = revenue × KPI%.
    """
    _name = "amocrm.dashboard"
    _description = "amoCRM KPI dashboard"

    # ------------------------------------------------------------------
    @api.model
    def _kpi_percent(self, conv_pct, revenue):
        """KPI % from the motivation sheet grid (1..7% × 10..90 mln).
        Below-grid values (conversion < 1% or revenue < 10 mln) → 0."""
        rev_mln = (revenue or 0.0) / 1_000_000.0
        if conv_pct < 1 or rev_mln < 10:
            return 0.0
        conv_step = min(7, int(conv_pct))
        rev_bucket = min(90, int(rev_mln // 10) * 10)
        return 12.0 - 0.5 * ((90 - rev_bucket) / 10.0) - 1.0 * (7 - conv_step)

    @api.model
    def _fetch_status_map(self):
        """{(pipeline_id, status_id): {label, color, order}} from amoCRM."""
        data = self.env["amocrm.connector"]._request("/api/v4/leads/pipelines")
        status_map = {}
        for p in (data.get("_embedded") or {}).get("pipelines") or []:
            for s in (p.get("_embedded") or {}).get("statuses") or []:
                status_map[(p.get("id"), s.get("id"))] = {
                    "label": "%s / %s" % (p.get("name"), s.get("name")),
                    "color": s.get("color") or "#e0e0e0",
                    "order": (p.get("sort") or 0) * 100000 + (s.get("sort") or 0),
                }
        return status_map

    @api.model
    def _fetch_leads(self, from_ts, to_ts, manager_id=False):
        connector = self.env["amocrm.connector"]
        leads, page = [], 1
        while page <= MAX_PAGES:
            params = {
                "filter[created_at][from]": from_ts,
                "filter[created_at][to]": to_ts,
                "limit": 250,
                "page": page,
            }
            if manager_id:
                params["filter[responsible_user_id]"] = int(manager_id)
            data = connector._request("/api/v4/leads", params=params)
            batch = (data.get("_embedded") or {}).get("leads") or []
            leads.extend(batch)
            if len(batch) < 250 or not ((data.get("_links") or {}).get("next")):
                break
            page += 1
        return leads

    @api.model
    def _lead_course(self, lead):
        for cf in lead.get("custom_fields_values") or []:
            if cf.get("field_name") == COURSE_FIELD_NAME:
                values = cf.get("values") or []
                if values:
                    return str(values[0].get("value") or "")
        return ""

    # ------------------------------------------------------------------
    @api.model
    def get_kpi_data(self, date_from, date_to, manager_id=False):
        """Aggregate per-manager KPI data for the period (dates 'YYYY-MM-DD')."""
        if not self.env.user.has_group("amocrm_connector.group_amocrm_user"):
            raise AccessError(_("amoCRM KPI dashboard uchun sizda rol yo'q."))
        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d")
            d_to = datetime.strptime(date_to, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise UserError(_("Sana formati noto'g'ri."))
        if d_from > d_to:
            raise UserError(_("Boshlanish sanasi tugash sanasidan keyin bo'lmasin."))
        from_ts = int(d_from.timestamp())
        to_ts = int((d_to + timedelta(days=1)).timestamp()) - 1

        status_map = self._fetch_status_map()
        leads = self._fetch_leads(from_ts, to_ts, manager_id=manager_id)

        # manager names from the synced amocrm.employee mirror
        emp_names = {
            e.amocrm_id: e.name
            for e in self.env["amocrm.employee"].sudo().search([])
        }

        managers = {}
        for lead in leads:
            uid = lead.get("responsible_user_id") or 0
            m = managers.setdefault(uid, {
                "id": uid,
                "name": emp_names.get(uid) or ("ID %s" % uid),
                "total": 0, "won": 0, "lost": 0, "active": 0,
                "revenue": 0.0,
                "_stages": {}, "_courses": {},
            })
            m["total"] += 1
            price = float(lead.get("price") or 0)
            status_id = lead.get("status_id")
            pipeline_id = lead.get("pipeline_id")

            if status_id == WON_STATUS:
                m["won"] += 1
                m["revenue"] += price
                course = self._lead_course(lead) or _("Kurs tanlanmagan")
                c = m["_courses"].setdefault(course, {"count": 0, "amount": 0.0})
                c["count"] += 1
                c["amount"] += price
            elif status_id == LOST_STATUS:
                m["lost"] += 1
            else:
                m["active"] += 1

            meta = status_map.get((pipeline_id, status_id)) or {
                "label": _("Noma'lum bosqich"), "color": "#e0e0e0", "order": 9e9,
            }
            key = (pipeline_id, status_id)
            st = m["_stages"].setdefault(key, {
                "label": meta["label"], "color": meta["color"],
                "order": meta["order"], "count": 0, "amount": 0.0,
                "won": status_id == WON_STATUS, "lost": status_id == LOST_STATUS,
            })
            st["count"] += 1
            st["amount"] += price

        result_managers = []
        for m in managers.values():
            conv = (m["won"] * 100.0 / m["total"]) if m["total"] else 0.0
            kpi = self._kpi_percent(conv, m["revenue"])
            stages = sorted(m.pop("_stages").values(), key=lambda s: s["order"])
            courses = [
                {"name": name, "count": c["count"], "amount": c["amount"]}
                for name, c in sorted(
                    m.pop("_courses").items(), key=lambda kv: -kv[1]["amount"]
                )
            ]
            m.update({
                "conversion": round(conv, 2),
                "kpi_pct": round(kpi, 2),
                "bonus": round(m["revenue"] * kpi / 100.0, 0),
                "stages": stages,
                "courses": courses,
            })
            result_managers.append(m)
        result_managers.sort(key=lambda m: (-m["revenue"], -m["won"], -m["total"]))

        totals = {
            "total": sum(m["total"] for m in result_managers),
            "won": sum(m["won"] for m in result_managers),
            "lost": sum(m["lost"] for m in result_managers),
            "revenue": sum(m["revenue"] for m in result_managers),
            "bonus": sum(m["bonus"] for m in result_managers),
        }
        totals["conversion"] = round(
            totals["won"] * 100.0 / totals["total"], 2
        ) if totals["total"] else 0.0

        return {
            "date_from": date_from,
            "date_to": date_to,
            "managers": result_managers,
            "totals": totals,
            "lead_count": len(leads),
        }
