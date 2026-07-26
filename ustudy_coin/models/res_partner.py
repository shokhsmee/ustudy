# -*- coding: utf-8 -*-
import json

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    homework_submission_ids = fields.One2many(
        "edu.homework.submission", "student_id",
        string="Vazifa topshiriqlari",
    )
    coin_total = fields.Integer(
        string="Jami coin", compute="_compute_coin_data",
        help="Barcha vazifalardan yig'ilgan coinlar (XP) yig'indisi.",
    )
    coin_data_json = fields.Text(
        string="Coin ma'lumotlari (JSON)", compute="_compute_coin_data",
    )

    def action_view_coins(self):
        """Smart button: open the animated full-page coin dashboard."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "ustudy_coin.coin_dashboard",
            "name": "Coin tizimi — %s" % (self.name or ""),
            "params": {"partner_id": self.id},
        }

    def action_view_coin_list(self):
        """Plain list of the coin ledger (homework submissions)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Coin tizimi — %s" % (self.name or ""),
            "res_model": "edu.homework.submission",
            "views": [
                (self.env.ref("ustudy_coin.view_homework_submission_coin_list").id, "list"),
                (False, "form"),
            ],
            "domain": [("student_id", "=", self.id)],
            "context": {"create": False},
        }

    def _compute_coin_data(self):
        state_labels = {
            "not_submitted": "Topshirilmagan",
            "submitted": "Topshirilgan",
            "graded": "O'tgan",
            "failed": "Yiqilgan",
        }
        for partner in self:
            # sudo: the student card is opened by users (HR, admins, teachers)
            # who may lack read access on submissions; the coin tab must not
            # raise for them.
            subs = partner.sudo().homework_submission_ids
            if not partner.is_student or not subs:
                partner.coin_total = 0
                partner.coin_data_json = json.dumps({
                    "total": 0, "task_count": 0, "passed_count": 0,
                    "failed_count": 0, "avg_mark": 0.0, "rows": [],
                })
                continue

            # One row per homework: coins aggregate over its submissions
            # (resubmissions each carry their own awarded XP), ball/date/state
            # come from the newest submission.
            by_hw = {}
            for sub in subs.sorted(key=lambda s: (s.submit_date or fields.Datetime.now(), s.id)):
                hw = sub.homework_id
                row = by_hw.setdefault(hw.id, {
                    "homework": hw, "coins": 0, "mark": 0.0,
                    "state": "submitted", "date": False, "attempts": 0,
                })
                row["coins"] += sub.xp_amount or 0
                row["attempts"] += 1
                # sorted ascending → the last processed is the newest
                row["mark"] = sub.mark or 0.0
                row["state"] = sub.state or "submitted"
                row["date"] = sub.submit_date

            rows = []
            for row in by_hw.values():
                hw = row["homework"]
                dt = row["date"]
                if dt:
                    dt = fields.Datetime.context_timestamp(partner, dt)
                rows.append({
                    "task": hw.name or "-",
                    "lesson": hw.lesson_label or "",
                    "group": hw.group_id.name if hw.group_id else "",
                    "date": dt.strftime("%d.%m.%Y %H:%M") if dt else "",
                    "sort": dt.isoformat() if dt else "",
                    "mark": round(row["mark"], 1),
                    "pass_mark": round(hw.pass_mark or 0.0, 1),
                    "coins": row["coins"],
                    "attempts": row["attempts"],
                    "state": row["state"],
                    "state_label": state_labels.get(row["state"], row["state"]),
                })
            rows.sort(key=lambda r: r["sort"], reverse=True)

            graded_marks = [r["mark"] for r in rows if r["state"] in ("graded", "failed")]
            total = sum(r["coins"] for r in rows)
            partner.coin_total = total
            partner.coin_data_json = json.dumps({
                "total": total,
                "task_count": len(rows),
                "passed_count": len([r for r in rows if r["state"] == "graded"]),
                "failed_count": len([r for r in rows if r["state"] == "failed"]),
                "avg_mark": round(sum(graded_marks) / len(graded_marks), 1) if graded_marks else 0.0,
                "rows": rows,
            })
