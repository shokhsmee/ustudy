from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EduGroupSchedule(models.Model):
    """Floating weekly schedule line for a group.

    Instead of hardcoding a single class time on the group, every recurring
    weekly slot is one record here. This lets a group meet, for example, on
    Monday 14:00-15:30 and Wednesday 18:00-19:30 with completely independent
    times (and optionally different rooms / teachers per slot).
    """

    _name = "edu.group.schedule"
    _description = "Group Schedule Line (Floating Schedule)"
    _order = "weekday_sequence asc, time_from asc"

    group_id = fields.Many2one(
        "edu.group",
        string="Group",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        related="group_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    active = fields.Boolean(default=True)

    weekday_id = fields.Many2one(
        "edu.weekday",
        string="Weekday",
        required=True,
        ondelete="restrict",
        index=True,
    )
    # Stored copy of the weekday sequence purely for ordering/grouping.
    weekday_sequence = fields.Integer(
        string="Weekday Sequence",
        related="weekday_id.sequence",
        store=True,
        index=True,
    )

    time_from = fields.Float(
        string="Start Time",
        required=True,
        help="Float time, e.g. 14.0 = 14:00, 14.5 = 14:30.",
    )
    time_to = fields.Float(
        string="End Time",
        required=True,
        help="Float time, e.g. 15.5 = 15:30.",
    )
    duration = fields.Float(
        string="Duration (h)",
        compute="_compute_duration",
        store=True,
    )

    # Per-slot overrides. When empty, the group defaults are used. This keeps
    # the common case simple while still allowing a Wednesday slot to live in a
    # different room than the Monday slot.
    room_id = fields.Many2one(
        "edu.room",
        string="Room",
        ondelete="set null",
        domain="[('company_id', '=', company_id)]",
    )
    effective_room_id = fields.Many2one(
        "edu.room",
        string="Effective Room",
        compute="_compute_effective",
        store=False,
        help="Slot room if set, otherwise the group's default room.",
    )
    teacher_id = fields.Many2one(
        "hr.employee",
        string="Teacher",
        ondelete="set null",
    )
    effective_teacher_id = fields.Many2one(
        "hr.employee",
        string="Effective Teacher",
        compute="_compute_effective",
        store=False,
        help="Slot teacher if set, otherwise the group's default teacher.",
    )

    name = fields.Char(string="Slot", compute="_compute_name", store=True)

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("time_from", "time_to")
    def _compute_duration(self):
        for rec in self:
            rec.duration = max((rec.time_to or 0.0) - (rec.time_from or 0.0), 0.0)

    @api.depends(
        "room_id",
        "teacher_id",
        "group_id.lesson_room",
        "group_id.teacher_id",
    )
    def _compute_effective(self):
        for rec in self:
            rec.effective_room_id = rec.room_id or rec.group_id.lesson_room
            rec.effective_teacher_id = rec.teacher_id or rec.group_id.teacher_id

    @api.depends("weekday_id.name", "time_from", "time_to")
    def _compute_name(self):
        for rec in self:
            if rec.weekday_id:
                rec.name = "%s %s-%s" % (
                    rec.weekday_id.name,
                    self._float_to_str(rec.time_from),
                    self._float_to_str(rec.time_to),
                )
            else:
                rec.name = _("New Slot")

    @staticmethod
    def _float_to_str(value):
        value = value or 0.0
        hours = int(value)
        minutes = int(round((value - hours) * 60))
        if minutes == 60:
            hours += 1
            minutes = 0
        return "%02d:%02d" % (hours, minutes)

    # ------------------------------------------------------------------
    # Data-integrity constraints (these are genuine hard rules, not the
    # soft capacity rule).
    # ------------------------------------------------------------------
    @api.constrains("time_from", "time_to")
    def _check_times(self):
        for rec in self:
            if not (0.0 <= rec.time_from < 24.0) or not (0.0 < rec.time_to <= 24.0):
                raise ValidationError(
                    _("Schedule times must be between 00:00 and 24:00.")
                )
            if rec.time_to <= rec.time_from:
                raise ValidationError(
                    _("Schedule end time must be after the start time.")
                )

    @api.constrains("weekday_id", "time_from", "time_to", "group_id")
    def _check_no_internal_overlap(self):
        """A single group cannot have two overlapping slots on the same day."""
        for rec in self:
            if not rec.weekday_id:
                continue
            siblings = rec.group_id.schedule_ids.filtered(
                lambda s: s.id != rec.id and s.weekday_id == rec.weekday_id
            )
            for sib in siblings:
                if rec.time_from < sib.time_to and sib.time_from < rec.time_to:
                    raise ValidationError(
                        _(
                            "Group '%(group)s' has overlapping slots on %(day)s "
                            "(%(a)s and %(b)s).",
                            group=rec.group_id.name,
                            day=rec.weekday_id.name,
                            a=rec.name,
                            b=sib.name,
                        )
                    )
