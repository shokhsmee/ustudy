# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    amocrm_base_url = fields.Char(
        string="amoCRM Base URL",
        config_parameter="amocrm.base_url",
        help="Masalan: https://sizning-subdomain.amocrm.ru",
    )
    amocrm_access_token = fields.Char(
        string="Access Token (uzoq muddatli)",
        config_parameter="amocrm.access_token",
        help="amoCRM'da yaratilgan uzoq muddatli (long-lived) integratsiya tokeni.",
    )
    amocrm_kpi_pipeline_ids = fields.Char(
        string="KPI voronkalari (pipeline ID)",
        config_parameter="amocrm.kpi_pipeline_ids",
        help="KPI dashboardlarda lidlar sanaladigan voronkalar, vergul bilan "
             "(standart: 7889006,10905214 = Call-Center + Sotuv). "
             "'all' deb yozilsa hamma voronkalar sanaladi.",
    )

    # --- buttons (persist the typed values first, then act) -----------
    def action_amocrm_test_connection(self):
        self.set_values()
        return self.env["amocrm.connector"].test_connection()

    def action_amocrm_sync_employees(self):
        self.set_values()
        return self.env["amocrm.connector"].sync_employees()

    def action_amocrm_open_employees(self):
        self.set_values()
        return self.env["ir.actions.act_window"]._for_xml_id(
            "amocrm_connector.action_amocrm_employees"
        )
