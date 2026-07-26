from odoo import api, fields, models
import secrets
import logging
import requests
import time
import json
from datetime import datetime, timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging
import requests


_logger = logging.getLogger(__name__)


class OnlinePBXSettings(models.Model):
    _name = 'onlinepbx.settings'
    _description = 'OnlinePBX Webhook & API Settings'
    _rec_name = 'name'

    name = fields.Char(default="OnlinePBX Settings", required=True)

    # Webhook token
    token = fields.Char(
        string="Webhook Token",
        help="Secret token used in webhook URL",
    )
    webhook_url = fields.Char(
        string="Webhook URL",
        compute="_compute_webhook_url",
        readonly=True,
    )

    # ---- API fields for history sync ----
    api_domain = fields.Char(
        string="API Domain",
        help="Your PBX domain, e.g. pbx123.onpbx.ru",
    )
    api_key = fields.Char(
        string="API Key (key_id:key)",
        help="API key in format key_id:key (see OnlinePBX API page).",
    )
    cdr_path = fields.Char(
        string="CDR Endpoint Path",
        default="/cdr.json",
        help="Relative path to CDR endpoint, e.g. /cdr.json . Adjust to match your OnlinePBX API docs.",
    )

    # ---- history sync date range (Sync Call History section) ----
    sync_date_from = fields.Date(
        string="Boshlanish sanasi",
        help="Qo'ng'iroqlar tarixini shu sanadan boshlab yuklash.",
    )
    sync_date_to = fields.Date(
        string="Tugash sanasi",
        help="Qo'ng'iroqlar tarixini shu sanagacha yuklash (kiritilmasa — bugun).",
    )
    sync_source = fields.Selection(
        [("pbx", "OnlinePBX API"), ("amocrm", "amoCRM")],
        string="Sync manbasi", default="pbx", required=True,
        help="Qo'ng'iroqlar tarixi qaysi manbadan yuklanadi. OnlinePBX domeni "
             "o'chirilgan (litsenziya yo'q) bo'lsa, amoCRM'dan yuklash mumkin — "
             "PBX→amoCRM integratsiyasi qo'ng'iroqlarni u yerga yozib boradi.",
    )

    # ---- amoCRM credentials (used when sync_source = amocrm) ----
    amocrm_subdomain = fields.Char(
        string="amoCRM Subdomain",
        help="Masalan: ustudyuz (https://ustudyuz.amocrm.ru uchun).",
    )
    amocrm_token = fields.Char(
        string="amoCRM Token",
        help="amoCRM uzoq muddatli token (долгосрочный токен) yoki OAuth2 "
             "access token. Sozlamalar → Integratsiyalar bo'limida yaratiladi.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('token'):
                vals['token'] = secrets.token_urlsafe(32)
        return super().create(vals_list)

    def write(self, vals):
        # If user clears token, regenerate
        if 'token' in vals and not vals['token']:
            vals['token'] = secrets.token_urlsafe(32)
        return super().write(vals)

    @api.depends('token')
    def _compute_webhook_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for rec in self:
            if rec.token:
                rec.webhook_url = f"{base_url}/onlinepbx/webhook/{rec.token}"
            else:
                rec.webhook_url = False

    # ======================================================================
    #  Call history sync via OnlinePBX HTTP API v2
    #  Docs: https://api.onlinepbx.ru (api-scheme.yaml),
    #  endpoint POST /{domain}/mongo_history/search.json.
    #  API hard limit: max 1 WEEK between start_stamp_from and start_stamp_to
    #  per request (longer → the API silently returns only the LAST week), so
    #  arbitrary ranges are fetched in ≤1-week windows.
    # ======================================================================

    API_MAX_WINDOW = 7 * 24 * 60 * 60  # 1 week, per official spec

    def _opbx_auth_header(self):
        """POST /auth.json with the panel auth_key → 'key_id:key' string for
        the x-pbx-authentication header."""
        self.ensure_one()
        if not self.api_domain or not self.api_key:
            raise UserError(_("Сначала заполните API Domain и API Key (auth_key) в OnlinePBX Settings."))

        auth_url = f"https://api2.onlinepbx.ru/{self.api_domain}/auth.json"
        try:
            auth_resp = requests.post(
                auth_url, data={"auth_key": self.api_key, "new": "true"}, timeout=30,
            )
        except Exception as e:
            _logger.exception("OnlinePBX auth error: %s", e)
            raise UserError(_("HTTP error calling OnlinePBX auth API: %s") % e)

        if auth_resp.status_code != 200:
            _logger.error("OnlinePBX auth: status %s, body: %s", auth_resp.status_code, auth_resp.text)
            raise UserError(_("OnlinePBX auth returned %s: %s") % (auth_resp.status_code, auth_resp.text))

        try:
            auth_data = auth_resp.json()
        except Exception:
            _logger.exception("OnlinePBX auth: cannot parse JSON: %s", auth_resp.text[:1000])
            raise UserError(_("Не удалось распарсить ответ auth.json от OnlinePBX"))

        if str(auth_data.get("status")) != "1":
            # e.g. DISABLED_DOMAIN when the PBX account is deactivated
            raise UserError(_("Авторизация не удалась: %s") % auth_data)

        return f"{auth_data['data']['key_id']}:{auth_data['data']['key']}"

    def _opbx_fetch_window(self, api_key_header, from_ts, to_ts):
        """One mongo_history/search.json request; window must be ≤ 1 week."""
        self.ensure_one()
        cdr_url = f"https://api2.onlinepbx.ru/{self.api_domain}/mongo_history/search.json"
        payload = {"start_stamp_from": from_ts, "start_stamp_to": to_ts}
        headers = {
            "x-pbx-authentication": api_key_header,
            "Accept": "application/json",
        }
        _logger.info("OnlinePBX sync: POST %s payload=%s", cdr_url, payload)

        try:
            resp = requests.post(cdr_url, headers=headers, data=payload, timeout=60)
        except Exception as e:
            _logger.exception("OnlinePBX sync: HTTP error: %s", e)
            raise UserError(_("HTTP error calling OnlinePBX API: %s") % e)

        if resp.status_code != 200:
            _logger.error("OnlinePBX sync: status %s, body: %s", resp.status_code, resp.text)
            raise UserError(_("OnlinePBX API returned %s: %s") % (resp.status_code, resp.text))

        try:
            data = resp.json()
        except Exception:
            _logger.exception("OnlinePBX sync: parse JSON error: %s", resp.text[:1000])
            raise UserError(_("Не удалось распарсить JSON ответ от OnlinePBX"))

        if isinstance(data, dict) and str(data.get("status")) != "1":
            raise UserError(_("OnlinePBX API xatosi: %s") % data)

        calls = data.get("data", []) if isinstance(data, dict) else data
        if isinstance(calls, dict):
            calls = calls.get("calls") or calls.get("results") or calls.get("items") or []
        if not isinstance(calls, list):
            _logger.error("OnlinePBX sync: unexpected format: %s", data)
            raise UserError(_("Неожиданный формат ответа mongo_history/search.json"))
        return calls

    def _sync_history_range(self, from_ts, to_ts):
        """Fetch [from_ts, to_ts] in ≤1-week windows, upsert by uuid."""
        self.ensure_one()
        api_key_header = self._opbx_auth_header()
        Call = self.env["onlinepbx.call"].sudo()
        created = updated = 0

        win_from = from_ts
        while win_from < to_ts:
            win_to = min(win_from + self.API_MAX_WINDOW, to_ts)
            calls = self._opbx_fetch_window(api_key_header, win_from, win_to)
            _logger.info(
                "OnlinePBX sync window %s..%s: %s calls", win_from, win_to, len(calls),
            )
            for item in calls:
                if not isinstance(item, dict):
                    continue
                uuid = item.get("uuid") or item.get("_id")
                if not uuid:
                    continue
                vals = self._prepare_call_vals_from_cdr(item)
                call = Call.search([("name", "=", uuid)], limit=1)
                if call:
                    call.write(vals)
                    updated += 1
                else:
                    Call.create(vals)
                    created += 1
            win_from = win_to

        _logger.info("OnlinePBX sync done: created=%s, updated=%s", created, updated)
        return created, updated

    def _sync_notification(self, created, updated, label):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OnlinePBX Sync"),
                "message": _("Yaratildi: %(c)s, yangilandi: %(u)s (%(label)s).") % {
                    "c": created, "u": updated, "label": label,
                },
                "type": "success",
                "sticky": False,
            },
        }

    def _dispatch_sync_range(self, from_ts, to_ts):
        """Route the range sync to the configured source."""
        self.ensure_one()
        if self.sync_source == "amocrm":
            return self._amocrm_sync_range(from_ts, to_ts)
        return self._sync_history_range(from_ts, to_ts)

    def action_sync_last_7_days(self):
        """Fetch last 7 days of calls from the configured source."""
        self.ensure_one()
        now_ts = int(time.time())
        created, updated = self._dispatch_sync_range(now_ts - self.API_MAX_WINDOW, now_ts)
        return self._sync_notification(created, updated, _("oxirgi 7 kun"))

    def action_sync_history(self):
        """Fetch the configured [sync_date_from, sync_date_to] range from the
        configured source (PBX: chunked into 1-week API windows)."""
        self.ensure_one()
        if not self.sync_date_from:
            raise UserError(_("Boshlanish sanasini kiriting."))
        date_to = self.sync_date_to or fields.Date.context_today(self)
        if self.sync_date_from > date_to:
            raise UserError(_("Boshlanish sanasi tugash sanasidan keyin bo'lishi mumkin emas."))

        from_ts = int(datetime.combine(self.sync_date_from, datetime.min.time()).timestamp())
        # inclusive end of day, capped at "now"
        to_ts = min(
            int(datetime.combine(date_to, datetime.max.time()).timestamp()),
            int(time.time()),
        )
        created, updated = self._dispatch_sync_range(from_ts, to_ts)
        return self._sync_notification(
            created, updated, f"{self.sync_date_from} — {date_to}",
        )

    # ======================================================================
    #  amoCRM source: calls live as call_in/call_out NOTES on contacts/leads
    #  (API v4, GET /api/v4/{entity}/notes, Bearer token, limit ≤250/page).
    #  Useful when the OnlinePBX domain is disabled but the PBX→amoCRM
    #  integration already stored the calls (with recording links) in amoCRM.
    # ======================================================================

    def _amocrm_base_url(self):
        self.ensure_one()
        if not self.amocrm_subdomain or not self.amocrm_token:
            raise UserError(_("Sync manbasi amoCRM: avval amoCRM Subdomain va Token kiriting."))
        sub = self.amocrm_subdomain.strip().replace("https://", "").split(".")[0]
        return f"https://{sub}.amocrm.ru"

    def _amocrm_fetch_call_notes(self, entity, from_ts, to_ts):
        """All call_in/call_out notes of one entity type in the range
        (paginated; amoCRM answers 204 when a page is empty)."""
        base = self._amocrm_base_url()
        headers = {"Authorization": f"Bearer {self.amocrm_token.strip()}"}
        url = f"{base}/api/v4/{entity}/notes"
        notes, page = [], 1
        while page <= 400:  # hard stop: 400 pages × 250 = 100k notes
            params = {
                "filter[note_type][0]": "call_in",
                "filter[note_type][1]": "call_out",
                "filter[updated_at][from]": from_ts,
                "filter[updated_at][to]": to_ts,
                "limit": 250,
                "page": page,
            }
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=60)
            except Exception as e:
                _logger.exception("amoCRM sync: HTTP error: %s", e)
                raise UserError(_("HTTP error calling amoCRM API: %s") % e)

            if resp.status_code == 204:
                break  # no (more) results
            if resp.status_code == 401:
                raise UserError(_("amoCRM token noto'g'ri yoki muddati o'tgan (401)."))
            if resp.status_code != 200:
                _logger.error("amoCRM sync: status %s, body: %s", resp.status_code, resp.text[:500])
                raise UserError(_("amoCRM API returned %s: %s") % (resp.status_code, resp.text[:500]))

            try:
                payload = resp.json()
            except Exception:
                raise UserError(_("amoCRM javobini o'qib bo'lmadi (JSON emas)."))

            batch = (payload.get("_embedded") or {}).get("notes") or []
            notes.extend(batch)
            if len(batch) < 250 or not (payload.get("_links") or {}).get("next"):
                break
            page += 1
        return notes

    def _amocrm_sync_range(self, from_ts, to_ts):
        """Upsert calls from amoCRM notes (contacts + leads) by uniq/note id."""
        self.ensure_one()
        Call = self.env["onlinepbx.call"].sudo()
        created = updated = 0
        for entity in ("contacts", "leads"):
            notes = self._amocrm_fetch_call_notes(entity, from_ts, to_ts)
            _logger.info("amoCRM sync %s: %s call notes", entity, len(notes))
            for note in notes:
                if not isinstance(note, dict):
                    continue
                vals = self._prepare_call_vals_from_amocrm(note)
                if not vals:
                    continue
                call = Call.search([("name", "=", vals["name"])], limit=1)
                if call:
                    call.write(vals)
                    updated += 1
                else:
                    Call.create(vals)
                    created += 1
        _logger.info("amoCRM sync done: created=%s, updated=%s", created, updated)
        return created, updated

    def _prepare_call_vals_from_amocrm(self, note):
        """Map one amoCRM call note to onlinepbx.call vals."""
        params = note.get("params") or {}
        note_type = note.get("note_type")
        if note_type not in ("call_in", "call_out"):
            return False

        direction = "in" if note_type == "call_in" else "out"
        duration = int(params.get("duration") or 0)
        if duration > 0:
            state = "answered"
        elif direction == "in":
            state = "missed"
        else:
            state = "not_answered"

        start_dt = False
        ts = note.get("created_at")
        if ts:
            try:
                start_dt = datetime.utcfromtimestamp(int(ts))
            except Exception:
                start_dt = False

        phone = str(params.get("phone") or "")
        link = params.get("link") or ""

        # operator: responsible amoCRM user matched via hr.employee.amocrm_user_id
        amo_user = note.get("responsible_user_id") or note.get("created_by")
        employee = False
        if amo_user:
            employee = self.env["hr.employee"].sudo().search(
                [("amocrm_user_id", "=", int(amo_user))], limit=1,
            )

        return {
            "name": params.get("uniq") or f"amo-note-{note.get('id')}",
            "direction": direction,
            "state": state,
            "from_number": phone if direction == "in" else "",
            "to_number": phone if direction == "out" else "",
            "start_time": start_dt,
            "duration_seconds": duration,
            "recording_url": link,
            "download_url": link,
            "has_recording": bool(link),
            "raw_payload": json.dumps(note, ensure_ascii=False, default=str),
            "employee_id": employee.id if employee else False,
        }

    # map ONE HTTP-API call record -> onlinepbx.call
    def _prepare_call_vals_from_cdr(self, item):
        """Map a mongo_history/search.json record to onlinepbx.call vals.

        Per the official response schema the talk time field is
        `user_talk_time` (NOT `billsec` — that was the deprecated
        /history/search.json), and `accountcode` may be any of
        inbound/outbound/local/missed/contacted/not_contacted/not_answered.
        """
        start_dt = False
        ts = item.get("start_stamp")
        if ts:
            try:
                start_dt = datetime.utcfromtimestamp(int(ts))
            except Exception:
                start_dt = False

        talk = int(item.get("user_talk_time") or item.get("billsec") or 0)

        acc = (item.get("accountcode") or "").lower()
        if acc in ("inbound", "missed", "contacted", "not_contacted"):
            direction = "in"
        elif acc in ("outbound", "not_answered"):
            direction = "out"
        elif acc == "local":
            direction = "local"
        else:
            direction = "in"

        if talk > 0:
            state = "answered"
        elif direction == "in":
            state = "missed"
        else:
            state = "not_answered"

        caller = str(item.get("caller_id_number") or "")
        callee = str(item.get("destination_number") or "")

        # extension detection & employee match — same rules as the webhook
        ext = False
        if direction == "in":
            ext = callee
        elif direction == "out":
            ext = caller
        elif direction == "local":
            if caller and len(caller) <= 4:
                ext = caller
            elif callee and len(callee) <= 4:
                ext = callee
        ext = ext.strip() if ext else False

        employee = False
        if ext:
            employee = self.env["hr.employee"].sudo().search(
                [("pbx_extension", "=", ext)], limit=1,
            )

        return {
            "name": item.get("uuid") or item.get("_id") or "PBX Call",
            "direction": direction,
            "state": state,
            "from_number": caller,
            "to_number": callee,
            "external_number": item.get("gateway"),
            "start_time": start_dt,
            "duration_seconds": talk,
            "has_recording": bool(item.get("rec_enabled")),
            "raw_payload": json.dumps(item, ensure_ascii=False, default=str),
            "employee_extension": ext,
            "employee_id": employee.id if employee else False,
        }
