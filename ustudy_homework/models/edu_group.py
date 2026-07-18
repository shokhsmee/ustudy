from odoo import fields, models, _


class EduGroup(models.Model):
    _inherit = "edu.group"

    def _compute_homework_timetable_count(self):
        # Topshiriqlar smart button opens the group's generated lessons with
        # their vazifa columns — count matches the rows shown (non-cancelled
        # lessons).
        Timetable = self.env["edu.timetable"]
        for g in self:
            g.homework_timetable_count = Timetable.search_count([
                ("group_id", "=", g.id),
                ("state", "!=", "cancelled"),
            ]) if isinstance(g.id, int) else 0

    def action_view_group_homeworks(self):
        """Topshiriqlar: every generated lesson of the group, one row each,
        with its slide, dars status and — once the teacher assigned one via
        the Darsni yakunlash wizard — the vazifa columns (berilgan vaqt,
        deadline, bajarish holati, tekshirilmagan). No vazifa yet -> those
        columns stay empty."""
        self.ensure_one()
        return {
            "name": _("Topshiriqlar - %s") % self.name,
            "type": "ir.actions.act_window",
            "res_model": "edu.timetable",
            "view_mode": "list,form",
            "views": [
                (self.env.ref("ustudy_homework.view_edu_timetable_group_tasks_list").id, "list"),
                (self.env.ref("ustudy_group.view_edu_timetable_form").id, "form"),
            ],
            "domain": [
                ("group_id", "=", self.id),
                ("state", "!=", "cancelled"),
            ],
            "context": {"default_group_id": self.id},
        }
