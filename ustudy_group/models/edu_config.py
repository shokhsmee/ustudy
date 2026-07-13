# -*- coding: utf-8 -*-
from odoo import models, fields, api


class EduConfig(models.Model):
    _name = 'edu.config'
    _description = 'Education Center Configuration'
    _rec_name = 'id'
    
    lessons_per_module = fields.Integer(
        string='Lessons Per Module',
        default=12,
        required=True,
        help='Number of lessons in one module (default: 12)'
    )
    
    module_price = fields.Float(
        string='Module Price',
        default=2000000.0,
        required=True,
        help='Price for one module (default: 2,000,000)'
    )
    
    partial_payment_lesson = fields.Integer(
        string='Partial Payment Warning (Lesson #)',
        default=3,
        required=True,
        help='Warn if student has not paid by this lesson number'
    )
    
    full_payment_lesson = fields.Integer(
        string='Full Payment Deadline (Lesson #)',
        default=5,
        required=True,
        help='Student will be frozen if not paid by this lesson number'
    )

    max_join_lesson = fields.Integer(
        string='Student Join Deadline (Lesson #)',
        default=4,
        required=True,
        help='New students can be added to a running group only within the first '
             'N lessons of the current module (default: 4)'
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        string='Currency'
    )
    
    _sql_constraints = [
        ('company_unique', 'unique(company_id)', 'Only one configuration per company is allowed!')
    ]
    
    @api.model
    def get_config(self):
        """Get or create configuration for current company"""
        config = self.search([('company_id', '=', self.env.company.id)], limit=1)
        if not config:
            config = self.create({
                'company_id': self.env.company.id,
                'lessons_per_module': 12,
                'module_price': 2000000.0,
                'partial_payment_lesson': 3,
                'full_payment_lesson': 5,
            })
        return config
    
    def action_open_config(self):
        config = self.get_config()
        return {
            "type": "ir.actions.act_window",
            "name": "Education Configuration",
            "res_model": "edu.config",
            "view_mode": "form",
            "res_id": config.id,
            "target": "current",
        }