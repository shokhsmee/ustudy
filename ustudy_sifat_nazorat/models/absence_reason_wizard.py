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
    description = fields.Text(string="Tavsif")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line_id = res.get("line_id") or self.env.context.get("default_line_id")
        if line_id and "reason" in fields_list and not res.get("reason"):
            line = self.env["edu.attendance.line"].browse(line_id)
            if line.absence_reason:
                res["reason"] = line.absence_reason
        return res

    def action_confirm(self):
        self.ensure_one()
        # writing the line syncs / creates the Sifat Nazorat record
        self.line_id.write({"absence_reason": self.reason})
        if self.description:
            sn = self.env["edu.sifat.nazorat"].sudo().search(
                [("attendance_line_id", "=", self.line_id.id)], limit=1,
            )
            if sn:
                sn.write({"description": self.description})
        return {"type": "ir.actions.act_window_close"}
