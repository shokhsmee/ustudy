/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

function toISO(d) {
    return d.toISOString().slice(0, 10);
}

export class DarsJadvaliBoard extends Component {
    static template = "ustudy_dars_jadvali.Board";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        const today = new Date();
        const monday = new Date(today);
        monday.setDate(today.getDate() - ((today.getDay() + 6) % 7));
        const saturday = new Date(monday);
        saturday.setDate(monday.getDate() + 5);

        this.state = useState({
            loading: true,
            data: null,
            filters: {
                date_from: toISO(monday),
                date_to: toISO(saturday),
                room_id: "",
                teacher_id: "",
                group_id: "",
                parity: "",
                slot: "",
            },
        });

        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const f = this.state.filters;
        this.state.data = await this.orm.call("dars.jadvali.board", "get_board_data", [
            {
                date_from: f.date_from || false,
                date_to: f.date_to || false,
                room_id: f.room_id ? parseInt(f.room_id) : false,
                teacher_id: f.teacher_id ? parseInt(f.teacher_id) : false,
                group_id: f.group_id ? parseInt(f.group_id) : false,
                parity: f.parity || false,
                slot: f.slot !== "" ? parseInt(f.slot) : false,
            },
        ]);
        this.state.loading = false;
    }

    onFilterChange() {
        this.load();
    }

    resetFilters() {
        const f = this.state.filters;
        f.room_id = f.teacher_id = f.group_id = f.parity = f.slot = "";
        this.load();
    }

    shiftWeek(direction) {
        const f = this.state.filters;
        const from = new Date(f.date_from);
        const to = new Date(f.date_to);
        from.setDate(from.getDate() + 7 * direction);
        to.setDate(to.getDate() + 7 * direction);
        f.date_from = toISO(from);
        f.date_to = toISO(to);
        this.load();
    }

    pct(fakt, reja) {
        if (!reja) {
            return "0%";
        }
        return Math.round((fakt * 100) / reja) + "%";
    }

    async openCard(card) {
        const action = await this.orm.call("dars.jadvali.board", "open_lesson_wizard", [
            card.group_id,
            card.timetable_ids,
        ]);
        this.action.doAction(action);
    }
}

registry.category("actions").add("ustudy_dars_jadvali.board", DarsJadvaliBoard);
