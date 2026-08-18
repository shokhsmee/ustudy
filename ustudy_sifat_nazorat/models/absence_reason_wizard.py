# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AbsenceReasonWizard(models.TransientModel):
    """Sababli/Sababsiz selection for one absent student."""
    _name = "edu.absence.reason.wizard"
    _description = "Kelmaganlik sababi tanlash"

    line_id = fields.Many2one(
        "edu.attendance.line", string="Davomat qatori", required=True,
        ondelete="cascade", readonly=True,
    )
    student_name = fields.Char(
        related="line_id.student_name", string="O'quvchi", readonly=True,
    )
    reason = fields.Selection(
        [("sababli", "Sababli"), ("sababsiz", "Sababsiz")],
        string="Sabab tasnifi", required=True,
    )
    reason_ids = fields.Many2many(
        "edu.absence.reason",
        string="Sabablari",
        help="Kelmaslik sabablari — bir nechta tanlash mumkin.",
    )
    description = fields.Text(string="Tavsif")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line_id = res.get("line_id") or self.env.context.get("default_line_id")
        if line_id:
            line = self.env["edu.attendance.line"].browse(line_id)
            if "reason" in fields_list and not res.get("reason") and line.absence_reason:
                res["reason"] = line.absence_reason
            if "reason_ids" in fields_list and not res.get("reason_ids"):
                res["reason_ids"] = [(6, 0, line.absence_reason_ids.ids)]
            # The izoh lives on the linked Sifat Nazorat record, not on the
            # line — without this prefill a saved izoh looked lost on reopen.
            # sudo: same reasoning as action_confirm (teachers may not read
            # edu.sifat.nazorat directly).
            if "description" in fields_list and not res.get("description"):
                sn = self.env["edu.sifat.nazorat"].sudo().search(
                    [("attendance_line_id", "=", line.id)], limit=1,
                )
                if sn and sn.description:
                    res["description"] = sn.description
        return res

    def action_confirm(self):
        self.ensure_one()
        # writing the line syncs / creates the Sifat Nazorat record
        self.line_id.write({
            "absence_reason": self.reason,
            "absence_reason_ids": [(6, 0, self.reason_ids.ids)],
        })
        sn = self.env["edu.sifat.nazorat"].sudo().search(
            [("attendance_line_id", "=", self.line_id.id)], limit=1,
        )
        if sn:
            # unconditional so an existing izoh can also be cleared
            sn.write({"description": self.description or False})
        return {"type": "ir.actions.act_window_close"}
