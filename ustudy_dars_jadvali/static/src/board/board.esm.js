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
        if (card.kind === "booking") {
            // non-lesson room booking: open its own record so it can be
            // edited or released (deleted)
            this.action.doAction(
                {
                    type: "ir.actions.act_window",
                    name: card.purpose_label,
                    res_model: "dars.jadvali.booking",
                    res_id: card.booking_id,
                    views: [[false, "form"]],
                    target: "new",
                },
                { onClose: () => this.load() }
            );
            return;
        }
        const action = await this.orm.call("dars.jadvali.board", "open_lesson_wizard", [
            card.group_id,
            card.timetable_ids,
        ]);
        this.action.doAction(action);
    }

    openAddLesson(week, block, row, room) {
        // default date = first day of the clicked parity block in that week
        // (toq -> Monday, juft -> Tuesday); the wizard lets the user change it
        const d = new Date(week.date_from);
        if (block.parity === "juft") {
            d.setDate(d.getDate() + 1);
        }
        const startTime = row.start_min / 60;
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: "Xonani band qilish",
                res_model: "dars.jadvali.add.lesson.wizard",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_room_id: room.id,
                    default_lesson_date: toISO(d),
                    default_start_time: startTime,
                    default_end_time: startTime + 1.5,
                    // the board only adds lessons; full booking (majlis/
                    // konsultatsiya/mehmon) lives on Xonalar bandligi
                    default_dars_only: true,
                },
            },
            { onClose: () => this.load() }
        );
    }
}

registry.category("actions").add("ustudy_dars_jadvali.board", DarsJadvaliBoard);
