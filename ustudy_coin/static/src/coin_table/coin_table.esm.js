/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useRecordObserver } from "@web/model/relational_model/utils";
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";

const EMPTY = {
    total: 0,
    task_count: 0,
    passed_count: 0,
    failed_count: 0,
    avg_mark: 0,
    rows: [],
};

/**
 * Shared visual core of the "Coin tizimi" UI (KPI cards + animated table).
 * Rendered in two places:
 *  - CoinTable: form field widget on the student card tab (coin_data_json)
 *  - CoinDashboard: full-page client action opened by the Coin smart button
 * Both templates t-call ustudy_coin.CoinBody, which reads data/state/fmt/
 * rowDelay from the component.
 */
export class CoinBase extends Component {
    static props = ["*"];

    setup() {
        this.state = useState({ displayTotal: 0 });
        this._raf = null;
        onWillUnmount(() => {
            if (this._raf) {
                cancelAnimationFrame(this._raf);
            }
        });
    }

    get data() {
        return EMPTY;
    }

    startCountUp() {
        if (this._raf) {
            cancelAnimationFrame(this._raf);
            this._raf = null;
        }
        const target = this.data.total || 0;
        const duration = 900; // ms
        const start = performance.now();
        const step = (now) => {
            const t = Math.min((now - start) / duration, 1);
            // ease-out cubic
            const eased = 1 - Math.pow(1 - t, 3);
            this.state.displayTotal = Math.round(target * eased);
            this._raf = t < 1 ? requestAnimationFrame(step) : null;
        };
        this._raf = requestAnimationFrame(step);
    }

    fmt(n) {
        return (n || 0).toLocaleString("ru-RU");
    }

    rowDelay(index) {
        // staggered slide-in, capped so long lists don't take forever
        return `animation-delay: ${Math.min(index * 60, 900)}ms`;
    }
}

/** Field widget: renders the JSON computed field on the partner form. */
export class CoinTable extends CoinBase {
    static template = "ustudy_coin.CoinTable";

    setup() {
        super.setup();
        // Re-run the count-up whenever the record or its value changes (pager
        // navigation patches the component in place — a mount-only animation
        // would leave the previous student's total on screen).
        useRecordObserver((record) => {
            void record.data[this.props.name]; // subscribe to this field
            this.startCountUp();
        });
    }

    get data() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) {
            return EMPTY;
        }
        try {
            return JSON.parse(raw);
        } catch {
            return EMPTY;
        }
    }
}

/** Client action: full-page animated coin dashboard (Coin smart button). */
export class CoinDashboard extends CoinBase {
    static template = "ustudy_coin.CoinDashboard";

    setup() {
        super.setup();
        this.orm = useService("orm");
        const action = this.props.action || {};
        this.partnerId =
            (action.params && action.params.partner_id) ||
            (action.context && action.context.partner_id) ||
            false;
        this.state.data = null;
        this.state.partnerName = "";
        onWillStart(() => this.load());
        onMounted(() => this.startCountUp());
    }

    async load() {
        if (!this.partnerId) {
            this.state.data = EMPTY;
            return;
        }
        const [rec] = await this.orm.read(
            "res.partner",
            [this.partnerId],
            ["name", "coin_data_json"]
        );
        this.state.partnerName = (rec && rec.name) || "";
        try {
            this.state.data = rec && rec.coin_data_json ? JSON.parse(rec.coin_data_json) : EMPTY;
        } catch {
            this.state.data = EMPTY;
        }
    }

    get data() {
        return this.state.data || EMPTY;
    }
}

export const coinTableField = {
    component: CoinTable,
    supportedTypes: ["text"],
};

registry.category("fields").add("coin_table", coinTableField);
registry.category("actions").add("ustudy_coin.coin_dashboard", CoinDashboard);
