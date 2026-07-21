# -*- coding: utf-8 -*-
from odoo import models, fields


class CCPaymentType(models.Model):
    _name = 'cc.payment.type'
    _description = 'Payment Type'
    _order = 'sequence, name'

    name = fields.Char(string='Type Name', required=True, translate=True)
    code = fields.Char(string='Code')
    direction = fields.Selection([
        ('kirim', 'Kirim'),
        ('chiqim', 'Chiqim'),
    ], string="Yo'nalish", required=True, default='kirim',
        help="Bu to'lov turi Kirim (income) yoki Chiqim (expense) ekanligini bildiradi. "
             "Kirimlar oynasida faqat 'Kirim', Chiqimlar oynasida faqat 'Chiqim' turlari ko'rinadi.")
    type_category = fields.Selection([
        ('student', 'Student'),
        ('teacher', 'Teacher'),
        ('employee', 'Employee'),
        ('other', 'Other')
    ], string='Category', required=True, default='other')
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    description = fields.Text(string='Description')
    
    _sql_constraints = [
        ('name_unique', 'unique(name)', 'Payment type name must be unique!')
    ]