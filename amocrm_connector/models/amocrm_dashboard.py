# -*- coding: utf-8 -*-
import logging
import time as time_mod
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests

from odoo import api, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

WON_STATUS = 142   # amoCRM system id: "Успешно реализовано" (per-pipeline label varies)
LOST_STATUS = 143  # amoCRM system id: "Закрыто и не реализовано"
COURSE_FIELD_NAME = "Asosiy kursi"  # lead custom field (Important tab)
MAX_PAGES = 200  # 200 × 250 = 50k leads per load, hard stop
PAGE_LIMIT = 250
FETCH_WORKERS = 4  # amoCRM rate limit is 7 req/s per account — stay under it
REQUEST_TIMEOUT = 30

# Leads are counted only in these voronkas (sales flow); other pipelines
# (HR, SMS, Test...) would inflate lead counts and ruin conversion %.
# Override in Sozlamalar > amoCRM ("all" = no filter).
PARAM_PIPELINES = "amocrm.kpi_pipeline_ids"
DEFAULT_PIPELINE_IDS = "7889006,10905214"  # Call-Center + Sotuv

# Per-worker in-memory TTL cache: the dashboard is re-loaded far more often
# than amoCRM data meaningfully changes, and every load costs seconds of
# sequential-by-nature HTTP paging.
CACHE_TTL_LEADS = 120
CACHE_TTL_PIPELINES = 600
_TTL_CACHE = {}


def _cache_get(key):
    item = _TTL_CACHE.get(key)
    if item and item[0] > time_mod.monotonic():
        return item[1]
    _TTL_CACHE.pop(key, None)
    return None


def _cache_set(key, value, ttl):
    if len(_TTL_CACHE) > 64:
        now = time_mod.monotonic()
        for k in [k for k, v in _TTL_CACHE.items() if v[0] <= now]:
            _TTL_CACHE.pop(k, None)
    _TTL_CACHE[key] = (time_mod.monotonic() + ttl, value)


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
    def _kpi_pipeline_ids(self):
        """Pipeline (voronka) ids the KPI dashboards count leads in.
        Config param: comma-separated ids; "all" or any non-numeric value
        disables the filter."""
        raw = self.env["ir.config_parameter"].sudo().get_param(
            PARAM_PIPELINES, DEFAULT_PIPELINE_IDS) or ""
        ids = []
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        return ids

    @api.model
    def _fetch_status_map(self):
        """{(pipeline_id, status_id): {label, color, order}} from amoCRM."""
        base_url, _token = self.env["amocrm.connector"]._get_credentials()
        cache_key = ("status_map", base_url)
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        data = self.env["amocrm.connector"]._request("/api/v4/leads/pipelines")
        status_map = {}
        for p in (data.get("_embedded") or {}).get("pipelines") or []:
            for s in (p.get("_embedded") or {}).get("statuses") or []:
                status_map[(p.get("id"), s.get("id"))] = {
                    "label": "%s / %s" % (p.get("name"), s.get("name")),
                    "color": s.get("color") or "#e0e0e0",
                    "order": (p.get("sort") or 0) * 100000 + (s.get("sort") or 0),
                }
        _cache_set(cache_key, status_map, CACHE_TTL_PIPELINES)
        return status_map

    @api.model
    def _fetch_leads(self, from_ts, to_ts, manager_id=False):
        pipeline_ids = self._kpi_pipeline_ids()
        cache_key = ("leads", from_ts, to_ts,
                     int(manager_id or 0), tuple(pipeline_ids))
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        base_url, token = self.env["amocrm.connector"]._get_credentials()
        url = base_url + "/api/v4/leads"
        headers = {
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json",
        }
        base_params = {
            "filter[created_at][from]": from_ts,
            "filter[created_at][to]": to_ts,
            "limit": PAGE_LIMIT,
        }
        if manager_id:
            base_params["filter[responsible_user_id]"] = int(manager_id)
        for i, pid in enumerate(pipeline_ids):
            base_params["filter[pipeline_id][%d]" % i] = pid

        # Pages are fetched by a thread pool without touching self.env —
        # only plain requests calls happen in the workers.
        def fetch_page(page):
            params = dict(base_params, page=page)
            for attempt in (1, 2, 3):
                try:
                    resp = requests.get(url, headers=headers, params=params,
                                        timeout=REQUEST_TIMEOUT)
                except requests.RequestException as e:
                    if attempt == 3:
                        raise UserError(
                            _("amoCRM ga ulanib bo'lmadi: %s") % e)
                    time_mod.sleep(0.5 * attempt)
                    continue
                if resp.status_code == 204:
                    return []
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt == 3:
                        raise UserError(
                            _("amoCRM API xatosi (%s)") % resp.status_code)
                    time_mod.sleep(0.5 * attempt)
                    continue
                if resp.status_code == 401:
                    raise UserError(_(
                        "amoCRM: 401 Unauthorized — Access Token noto'g'ri "
                        "yoki muddati tugagan."))
                if not resp.ok:
                    raise UserError(
                        _("amoCRM API xatosi (%s)") % resp.status_code)
                try:
                    data = resp.json()
                except ValueError:
                    return []
                return (data.get("_embedded") or {}).get("leads") or []
            return []

        leads = []
        page = 1
        done = False
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            while not done and page <= MAX_PAGES:
                batch_pages = list(
                    range(page, min(page + FETCH_WORKERS, MAX_PAGES + 1)))
                futures = [pool.submit(fetch_page, p) for p in batch_pages]
                for fut in futures:
                    batch = fut.result()
                    leads.extend(batch)
                    if len(batch) < PAGE_LIMIT:
                        done = True
                page = batch_pages[-1] + 1

        _cache_set(cache_key, leads, CACHE_TTL_LEADS)
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
