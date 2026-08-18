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

export class SalesKpiDashboard extends Component {
    static template = "ustudy_sales.SalesKpiDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");

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
                "edu.sales.dashboard", "get_sales_kpi_data",
                [this.state.dateFrom, this.state.dateTo]
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

    convWidth(manager) {
        if (!manager.leads) {
            return manager.orders ? "100%" : "0%";
        }
        const pct = (manager.orders * 100) / manager.leads;
        return `${Math.min(100, Math.max(pct, 2)).toFixed(1)}%`;
    }
}

registry.category("actions").add("ustudy_sales.sales_kpi_dashboard", SalesKpiDashboard);
