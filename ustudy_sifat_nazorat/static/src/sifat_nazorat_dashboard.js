/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onPatched, onWillStart, useState } from "@odoo/owl";

// Mini dashboard above the Sifat Nazorat list: jami / sababli / sababsiz /
// tasniflanmagan counts, following the active search filters (same pattern
// as edu_finance's finance_dashboard_list).
export class SifatNazoratDashboardController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.snData = useState({ total: 0, sababli: 0, sababsiz: 0, unset: 0 });
        this._lastDomain = null;

        onWillStart(() => this._loadDashboard());
        onMounted(() => this._renderDashboard());
        onPatched(() => this._onPatched());
    }

    _getDomain() {
        try {
            return JSON.stringify(this.model.root.domain || []);
        } catch {
            return "[]";
        }
    }

    async _onPatched() {
        const currentDomain = this._getDomain();
        if (currentDomain !== this._lastDomain) {
            this._lastDomain = currentDomain;
            await this._loadDashboard();
        }
        this._renderDashboard();
    }

    async _loadDashboard() {
        let domain = [];
        try {
            domain = this.model.root.domain || [];
        } catch {
            domain = [];
        }
        try {
            const data = await this.orm.call(
                "edu.sifat.nazorat", "get_sn_dashboard", [domain], {}
            );
            this.snData.total = data.total || 0;
            this.snData.sababli = data.sababli || 0;
            this.snData.sababsiz = data.sababsiz || 0;
            this.snData.unset = data.unset || 0;
        } catch (e) {
            console.error("Sifat nazorat dashboard error:", e);
        }
    }

    _renderDashboard() {
        document.querySelectorAll(".o_sn_dashboard_banner").forEach((el) => el.remove());

        const root = document.querySelector(".o_list_view");
        if (!root) {
            return;
        }

        const d = this.snData;
        const banner = document.createElement("div");
        banner.className = "o_sn_dashboard_banner d-flex gap-3 px-3 pt-3 pb-2";
        banner.innerHTML = `
            <div class="o_group_dashboard_card flex-fill" style="background:#e8f4fd;">
                <div class="o_group_dashboard_icon"><i class="fa fa-user-times" style="color:#1565c0;"></i></div>
                <div class="o_group_dashboard_info">
                    <div class="o_group_dashboard_value" style="color:#1565c0;">${d.total}</div>
                    <div class="o_group_dashboard_label" style="color:#1565c0;">Jami kelmaganlar</div>
                </div>
            </div>
            <div class="o_group_dashboard_card flex-fill" style="background:#e8f5e9;">
                <div class="o_group_dashboard_icon"><i class="fa fa-medkit" style="color:#1b5e20;"></i></div>
                <div class="o_group_dashboard_info">
                    <div class="o_group_dashboard_value" style="color:#1b5e20;">${d.sababli}</div>
                    <div class="o_group_dashboard_label" style="color:#1b5e20;">Sababli</div>
                </div>
            </div>
            <div class="o_group_dashboard_card flex-fill" style="background:#fdecea;">
                <div class="o_group_dashboard_icon"><i class="fa fa-times-circle" style="color:#b71c1c;"></i></div>
                <div class="o_group_dashboard_info">
                    <div class="o_group_dashboard_value" style="color:#b71c1c;">${d.sababsiz}</div>
                    <div class="o_group_dashboard_label" style="color:#b71c1c;">Sababsiz</div>
                </div>
            </div>
            <div class="o_group_dashboard_card flex-fill" style="background:#fff8e1;">
                <div class="o_group_dashboard_icon"><i class="fa fa-question-circle" style="color:#e65100;"></i></div>
                <div class="o_group_dashboard_info">
                    <div class="o_group_dashboard_value" style="color:#e65100;">${d.unset}</div>
                    <div class="o_group_dashboard_label" style="color:#e65100;">Tasniflanmagan</div>
                </div>
            </div>
        `;
        root.insertBefore(banner, root.firstChild);
    }
}

export const SifatNazoratDashboardListView = {
    ...listView,
    Controller: SifatNazoratDashboardController,
};

registry.category("views").add("sifat_nazorat_dashboard_list", SifatNazoratDashboardListView);
