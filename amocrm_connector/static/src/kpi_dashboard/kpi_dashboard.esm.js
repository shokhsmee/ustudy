/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

function ymd(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

export class AmocrmKpiDashboard extends Component {
    static template = "amocrm_connector.KpiDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        const params = (this.props.action && this.props.action.params) || {};
        this.managerId = params.manager_id || false;
        this.managerName = params.manager_name || "";

        const now = new Date();
        const first = new Date(now.getFullYear(), now.getMonth(), 1);
        this.state = useState({
            loading: true,
            error: "",
            dateFrom: ymd(first),
            dateTo: ymd(now),
            data: null,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.data = await this.orm.call(
                "amocrm.dashboard", "get_kpi_data",
                [this.state.dateFrom, this.state.dateTo, this.managerId]
            );
        } catch (e) {
            this.state.error = (e.data && e.data.message) || e.message || String(e);
            this.state.data = null;
        }
        this.state.loading = false;
    }

    // ---- formatting helpers -------------------------------------------
    fmtInt(v) {
        return new Intl.NumberFormat("uz-UZ").format(Math.round(v || 0));
    }

    fmtMoney(v) {
        const n = v || 0;
        if (Math.abs(n) >= 1_000_000) {
            const mln = n / 1_000_000;
            return `${new Intl.NumberFormat("uz-UZ", { maximumFractionDigits: 2 }).format(mln)} mln`;
        }
        return this.fmtInt(n);
    }

    barWidth(stage, manager) {
        if (!manager.total) {
            return "0%";
        }
        const pct = (stage.count * 100) / manager.total;
        return `${Math.max(pct, 3).toFixed(1)}%`;
    }
}

registry.category("actions").add("amocrm_connector.kpi_dashboard", AmocrmKpiDashboard);
