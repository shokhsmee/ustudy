from odoo import api, fields, models


class EduRoom(models.Model):
    _name = 'edu.room'
    _description = 'Rooms'
    _order = 'sequence'

    name = fields.Char(string='Room Name', required=True)
    capacity = fields.Integer(
        string='Capacity',
        help="Maximum number of seats. Used as a soft limit (0 = unlimited). "
             "A group whose room is smaller than its 'Max Students' is capped "
             "by the room.",
    )
    sequence = fields.Integer(default=1)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True
    )

    # Reverse relations: groups that use this room either as their default
    # room or through a floating schedule slot.
    group_ids = fields.One2many(
        'edu.group',
        'lesson_room',
        string='Groups (default room)',
    )
    schedule_ids = fields.One2many(
        'edu.group.schedule',
        'room_id',
        string='Schedule Slots',
    )

    # Soft-capacity visibility at the room level.
    occupied_seats = fields.Integer(
        string='Occupied Seats',
        compute='_compute_occupancy',
        store=False,
        help="Active/frozen students across the groups whose default room "
             "is this room.",
    )
    is_over_capacity = fields.Boolean(
        string='Over Capacity',
        compute='_compute_occupancy',
        store=False,
    )

    @api.depends(
        'capacity',
        'group_ids.student_line_ids.state',
    )
    def _compute_occupancy(self):
        for room in self:
            occupied = sum(group._occupied_seats() for group in room.group_ids)
            room.occupied_seats = occupied
            room.is_over_capacity = bool(room.capacity) and occupied > room.capacity
