# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM_BASE_URL = "amocrm.base_url"
PARAM_TOKEN = "amocrm.access_token"
PARAM_LAST_SYNC = "amocrm.employees_last_sync"
REQUEST_TIMEOUT = 30


class AmocrmConnector(models.AbstractModel):
    """Thin HTTP client for the amoCRM REST API (v4).

    Authentication is a private-integration long-lived access token stored in
    ir.config_parameter (set from Settings > amoCRM). All API traffic goes
    through _request(); higher-level helpers (test_connection, sync_employees)
    build on it. No state is kept here — it is a stateless service model.
    """
    _name = "amocrm.connector"
    _description = "amoCRM API connector"

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------
    @api.model
    def _get_credentials(self):
        icp = self.env["ir.config_parameter"].sudo()
        base_url = (icp.get_param(PARAM_BASE_URL) or "").strip().rstrip("/")
        token = (icp.get_param(PARAM_TOKEN) or "").strip()
        if not base_url or not token:
            raise UserError(_(
                "amoCRM sozlanmagan. Sozlamalar > amoCRM bo'limida Base URL va "
                "Access Token ni kiriting."
            ))
        if not base_url.startswith("http"):
            base_url = "https://" + base_url
        return base_url, token

    @api.model
    def _request(self, path, method="GET", params=None, payload=None):
        base_url, token = self._get_credentials()
        url = base_url + path
        headers = {
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json",
        }
        try:
            resp = requests.request(
                method, url,
                headers=headers,
                params=params,
                data=json.dumps(payload) if payload is not None else None,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as e:
            _logger.warning("amoCRM request failed: %s %s -> %s", method, url, e)
            raise UserError(_("amoCRM ga ulanib bo'lmadi: %s") % e)

        if resp.status_code == 204:
            return {}
        if resp.status_code == 401:
            raise UserError(_(
                "amoCRM: 401 Unauthorized — Access Token noto'g'ri yoki muddati "
                "tugagan. Yangi uzoq muddatli tokenni kiriting."
            ))
        if not resp.ok:
            try:
                detail = resp.json()
            except ValueError:
                detail = (resp.text or "")[:500]
            raise UserError(_("amoCRM API xatosi (%(code)s): %(detail)s") % {
                "code": resp.status_code, "detail": detail,
            })
        try:
            return resp.json()
        except ValueError:
            return {}

    # ------------------------------------------------------------------
    # High-level actions
    # ------------------------------------------------------------------
    @api.model
    def test_connection(self):
        data = self._request("/api/v4/account")
        name = data.get("name") or data.get("subdomain") or "?"
        return self._notify(
            _("amoCRM ulanish muvaffaqiyatli"),
            _("Hisob: %s") % name, "success",
        )

    @api.model
    def sync_employees(self):
        Employee = self.env["amocrm.employee"]
        page, limit = 1, 250
        seen = created = updated = 0
        while True:
            data = self._request("/api/v4/users", params={
                "page": page, "limit": limit, "with": "role,group",
            })
            users = (data.get("_embedded") or {}).get("users") or []
            if not users:
                break
            for u in users:
                seen += 1
                vals = Employee._values_from_amocrm(u)
                rec = Employee.search([("amocrm_id", "=", u.get("id"))], limit=1)
                if rec:
                    rec.write(vals)
                    updated += 1
                else:
                    rec = Employee.create(vals)
                    created += 1
                rec._auto_match_user()
            if not ((data.get("_links") or {}).get("next")):
                break
            page += 1

        self.env["ir.config_parameter"].sudo().set_param(
            PARAM_LAST_SYNC, fields.Datetime.to_string(fields.Datetime.now())
        )
        return self._notify(
            _("amoCRM xodimlari sinxronlandi"),
            _("Jami: %(seen)s | Yangi: %(c)s | Yangilangan: %(u)s") % {
                "seen": seen, "c": created, "u": updated,
            },
            "success",
        )

    # ------------------------------------------------------------------
    @api.model
    def _notify(self, title, message, kind="info"):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": kind,
                "sticky": False,
            },
        }
