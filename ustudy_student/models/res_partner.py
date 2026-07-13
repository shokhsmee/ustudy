# ustudy_student/models/res_partner.py
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    # --- Student flag & relations (your existing code) -----------------------
    is_student = fields.Boolean(
        string="Is Student",
        help="If checked, this contact is considered a student.",
    )
    birth_date = fields.Date(string="Birth Date")

    slide_channel_partner_ids = fields.One2many(
        "slide.channel.partner",
        "partner_id",
        string="Kurslar (eLearning)",
    )

    enrollment_ids = fields.One2many(
        "edu.enrollment",
        "student_id",
        string="Course Enrollments",
    )

    status = fields.Selection(
        [
            ("active", "Active"),
            ("frozen", "Frozen"),
            ("graduated", "Graduated")
        ],
        default='active',
        string="Student Status"
    )

    total_courses = fields.Integer(
        string="Total Courses",
        compute="_compute_student_stats",
        store=False,
    )
    avg_progress = fields.Float(
        string="Average Progress (%)",
        compute="_compute_student_stats",
        store=False,
    )
    avg_mark = fields.Float(
        string="Average Mark",
        compute="_compute_student_stats",
        store=False,
    )
    
    cc_region_id = fields.Many2one(
        "cc.region",
        string="Tuman",
        domain="[('state_id', '=', state_id)]",
    )

    # --- Address tweak: default country = Uzbekistan ------------------------
    country_id = fields.Many2one(
        "res.country",
        string="Country",
        default=lambda self: self.env.ref(
            "base.uz", raise_if_not_found=False
        ) or self.env.company.country_id,
    )

    # --- Extra docs (passport etc.) ----------------------------------------
    passport_number = fields.Char(string="Passport Number")
    passport_file = fields.Binary(string="Passport Scan")
    passport_filename = fields.Char(string="Passport File Name")

    extra_doc_name = fields.Char(string="Extra Document Name")
    extra_doc_file = fields.Binary(string="Extra Document")
    extra_doc_filename = fields.Char(string="Extra Document File Name")


    is_online_education = fields.Boolean(
        string="Online Ta'lim",
        default=False,
    )

    group_names = fields.Char(
        string="Groups",
        compute="_compute_group_names",
        store=False,
    )

    @api.depends('is_student')
    def _compute_group_names(self):
        GroupLine = self.env['edu.group.student']
        for partner in self:
            if not partner.is_student:
                partner.group_names = False
                continue

            lines = GroupLine.search([
                ('student_id', '=', partner.id),
                ('company_id', '=', partner.company_id.id),
            ])
            group_names = lines.mapped('group_id.name')
            partner.group_names = ", ".join(group_names) if group_names else False



    # ---------------------------------------------------------------------
    # STATS
    # ---------------------------------------------------------------------
    @api.depends("enrollment_ids.progress")
    def _compute_student_stats(self):
        for partner in self:
            enrollments = partner.enrollment_ids
            partner.total_courses = len(enrollments)
            partner.avg_progress = (
                sum(e.progress for e in enrollments) / len(enrollments)
            ) if enrollments else 0.0
            partner.avg_mark = 0.0  # placeholder

    # ---------------------------------------------------------------------
    # PORTAL USER LIFECYCLE
    # ---------------------------------------------------------------------
    def _ensure_portal_user(self):
        """Create or update a portal user for this student partner.
        The user's active state is driven by is_online_education."""
        self.ensure_one()
        if not self.email:
            return None

        Users = self.env["res.users"].sudo()
        user_fields = Users._fields

        groups_field = next(
            (f for f in ("groups_id", "group_ids") if f in user_fields), None
        )
        if not groups_field:
            return None

        group_portal = self.env.ref("base.group_portal")
        group_user = self.env.ref("base.group_user")

        existing_linked = Users.with_context(active_test=False).search(
            [("partner_id", "=", self.id)], limit=1
        )
        if existing_linked:
            # Never modify internal (non-share) users
            if not existing_linked.share:
                return existing_linked
            existing_linked.write({
                "share": True,
                "active": self.is_online_education,
                groups_field: [(4, group_portal.id), (3, group_user.id)],
            })
            return existing_linked

        existing_login = Users.with_context(active_test=False).search(
            [("login", "=", self.email)], limit=1
        )
        if existing_login:
            # Never modify internal (non-share) users
            if not existing_login.share:
                return existing_login
            existing_login.write({
                "partner_id": self.id,
                "share": True,
                "active": self.is_online_education,
                groups_field: [(4, group_portal.id), (3, group_user.id)],
            })
            return existing_login

        vals = {
            "name": self.name or self.display_name,
            "login": self.email,
            "email": self.email,
            "partner_id": self.id,
            "share": True,
            "active": self.is_online_education,
            groups_field: [(6, 0, [group_portal.id])],
        }
        for fname, fval in [
            ("edu_role_portal", True), ("edu_role_user", False),
            ("edu_role_admin", False), ("edu_student", True),
        ]:
            if fname in user_fields:
                vals[fname] = fval

        user = Users.with_context(no_reset_password=True).create(vals)
        user.write({groups_field: [(3, group_user.id)]})
        return user

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.is_student and record.email:
                record._ensure_portal_user()
        return records

    def write(self, vals):
        is_student_toggling = "is_student" in vals
        is_online_toggling = "is_online_education" in vals

        # Online Ta'lim requires an email: block enabling it without one.
        if is_online_toggling and vals.get("is_online_education"):
            for record in self:
                resulting_email = vals.get("email", record.email)
                if not resulting_email:
                    raise UserError(_("Email kiritilishi shart"))

        pre_student = {}
        if is_student_toggling:
            pre_student = {r.id: r.is_student for r in self}

        result = super().write(vals)

        for record in self:
            if is_student_toggling and not pre_student.get(record.id) and record.is_student and record.email:
                record._ensure_portal_user()

            if is_online_toggling:
                user = self.env["res.users"].sudo().with_context(active_test=False).search(
                    [("partner_id", "=", record.id)], limit=1
                )
                if user and user.share:
                    user.write({"active": record.is_online_education})
                elif not user and record.is_student and record.email:
                    record._ensure_portal_user()

        return result

    # ---------------------------------------------------------------------
    # STUDENT PORTAL ACCESS (kept for backward compatibility)
    # ---------------------------------------------------------------------
    def action_grant_portal_access(self):
        self.ensure_one()

        if not self.is_student:
            raise UserError(_("Only students can be granted portal access."))

        if not self.email:
            raise UserError(
                _("Student '%s' must have an email to grant portal access.")
                % self.display_name
            )

        # If partner already linked to a user
        if self.user_ids:
            raise UserError(
                _("Student '%s' already has a user account.")
                % self.display_name
            )

        Users = self.env["res.users"].sudo()
        user_fields = Users._fields

        # Detect the correct groups m2m field name on this Odoo build
        groups_field = None
        if "groups_id" in user_fields:
            groups_field = "groups_id"
        elif "group_ids" in user_fields:
            groups_field = "group_ids"

        if not groups_field:
            raise UserError(
                _("Cannot set portal access: no groups field found on res.users.")
            )

        group_portal = self.env.ref("base.group_portal")
        group_user = self.env.ref("base.group_user")  # internal users

        # If another user already uses this login, don't try to create a new one
        existing_user = Users.search([("login", "=", self.email)], limit=1)
        if existing_user:
            # Never downgrade internal users to portal
            if not existing_user.share:
                raise UserError(
                    _("'%s' ichki foydalanuvchi (internal user). Portal accessga o'tkazib bo'lmaydi.")
                    % existing_user.name
                )
            # Option A: attach that user to this partner (recommended)
            existing_user.write({
                "partner_id": self.id,
                "share": True,
            })
            # Make portal, remove internal
            existing_user.write({
                groups_field: [(4, group_portal.id), (3, group_user.id)]
            })

            # Optional custom flags
            if "edu_role_portal" in user_fields:
                existing_user.write({"edu_role_portal": True})
            if "edu_role_user" in user_fields:
                existing_user.write({"edu_role_user": False})
            if "edu_role_admin" in user_fields:
                existing_user.write({"edu_role_admin": False})
            if "edu_student" in user_fields:
                existing_user.write({"edu_student": True})

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Success"),
                    "message": _("Portal user linked/updated for %s") % self.display_name,
                    "type": "success",
                    "sticky": False,
                },
            }

        # Create new portal user
        vals = {
            "name": self.name or self.display_name,
            "login": self.email,
            "email": self.email,
            "partner_id": self.id,
            "share": True,
            groups_field: [(6, 0, [group_portal.id])],
        }

        # Optional custom flags
        if "edu_role_portal" in user_fields:
            vals["edu_role_portal"] = True
        if "edu_role_user" in user_fields:
            vals["edu_role_user"] = False
        if "edu_role_admin" in user_fields:
            vals["edu_role_admin"] = False
        if "edu_student" in user_fields:
            vals["edu_student"] = True

        user = Users.create(vals)

        # Safety: ensure it's not internal
        user.write({groups_field: [(3, group_user.id)]})

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Success"),
                "message": _("Portal user created for %s") % self.display_name,
                "type": "success",
                "sticky": False,
            },
        }
        
    @api.onchange('state_id')
    def _onchange_state_id(self):
        # if you already override this in another module, merge logic
        if self.cc_region_id and self.cc_region_id.state_id != self.state_id:
            self.cc_region_id = False

    

    timetable_count = fields.Integer(
        string="Timetable Entries",
        compute="_compute_timetable_count",
        store=False,
    )
    
    @api.depends('is_student')
    def _compute_timetable_count(self):
        for partner in self:
            if partner.is_student:
                # Find all groups where this student is enrolled
                student_groups = self.env['edu.group.student'].search([
                    ('student_id', '=', partner.id)
                ]).mapped('group_id')
                
                # Count timetable entries for those groups
                partner.timetable_count = self.env['edu.timetable'].search_count([
                    ('group_id', 'in', student_groups.ids),
                    ('state', '!=', 'cancelled')
                ])
            else:
                partner.timetable_count = 0
    
    def action_view_student_timetable(self):
        """Open timetable entries for student's groups"""
        self.ensure_one()
        
        # Find all groups where this student is enrolled
        student_groups = self.env['edu.group.student'].search([
            ('student_id', '=', self.id)
        ]).mapped('group_id')
        
        return {
            'name': _('Timetable - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'edu.timetable',
            'view_mode': 'calendar,list,form',
            'domain': [
                ('group_id', 'in', student_groups.ids),
                ('state', '!=', 'cancelled')
            ],
            'context': {'create': False},
        }