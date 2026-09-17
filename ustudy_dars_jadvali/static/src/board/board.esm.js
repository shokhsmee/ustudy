/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { Component, onWillStart, useEffect, useRef, useState } from "@odoo/owl";

function toISO(d) {
    return d.toISOString().slice(0, 10);
}

/**
 * "Bo'sh joy topish": lists every gap of at least the picked duration in the
 * 08:00-22:00 board day, grouped by day then room. Clicking a gap hands it
 * back to the board, which opens the booking wizard prefilled with it.
 */
export class FreeSlotDialog extends Component {
    static template = "ustudy_dars_jadvali.FreeSlotDialog";
    static components = { Dialog };
    static props = {
        dateFrom: String,
        dateTo: String,
        rooms: Array,
        roomId: { type: String, optional: true },
        onPick: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            data: null,
            roomId: this.props.roomId || "",
            minMinutes: "90",
            dateFrom: this.props.dateFrom,
            dateTo: this.props.dateTo,
        });
        onWillStart(() => this.load());
    }

    get dialogTitle() {
        return "Bo'sh joy topish";
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call("dars.jadvali.board", "get_free_slots", [
            {
                date_from: this.state.dateFrom || false,
                date_to: this.state.dateTo || false,
                room_id: this.state.roomId ? parseInt(this.state.roomId) : false,
                min_minutes: parseInt(this.state.minMinutes),
            },
        ]);
        this.state.loading = false;
    }

    pick(day, room, win) {
        // start at the beginning of the gap, one slot of the picked length
        const length = parseInt(this.state.minMinutes);
        this.props.onPick({
            room_id: room.room_id,
            date: day.date,
            start_min: win.start_min,
            end_min: Math.min(win.start_min + length, win.end_min),
        });
        this.props.close();
    }
}

export class DarsJadvaliBoard extends Component {
    static template = "ustudy_dars_jadvali.Board";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.rootRef = useRef("root");

        // The three header rows are all position:sticky; without staggering
        // them they pile up on top:0 and the Reja/Fakt strip hides the room
        // names. Measure each row and hand its offset to CSS after every
        // render (heights change with zoom/font/room count, so no constants).
        useEffect(() => this.syncStickyHeader());

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

    syncStickyHeader() {
        const root = this.rootRef.el;
        if (!root) {
            return;
        }
        for (const table of root.querySelectorAll(".o_dj_table")) {
            let top = 0;
            for (const tr of table.querySelectorAll("thead tr")) {
                tr.style.setProperty("--dj-head-top", `${top}px`);
                top += tr.getBoundingClientRect().height;
            }
        }
    }

    // -------- mini dashboards --------
    deltaDir(stat) {
        if (stat.delta > 0) {
            return "up";
        }
        return stat.delta < 0 ? "down" : "flat";
    }

    deltaLabel(stat) {
        if (stat.delta > 0) {
            return "▲ +" + stat.delta;
        }
        return stat.delta < 0 ? "▼ " + stat.delta : "— 0";
    }

    // -------- free slot finder --------
    openFreeSlots() {
        this.dialog.add(FreeSlotDialog, {
            dateFrom: this.state.filters.date_from,
            dateTo: this.state.filters.date_to,
            rooms: this.state.data ? this.state.data.filter_options.rooms : [],
            roomId: this.state.filters.room_id,
            onPick: (sel) => this.openSlotWizard(sel),
        });
    }

    openSlotWizard(sel) {
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: "Xonani band qilish",
                res_model: "dars.jadvali.add.lesson.wizard",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_room_id: sel.room_id,
                    default_lesson_date: sel.date,
                    default_start_time: sel.start_min / 60,
                    default_end_time: sel.end_min / 60,
                    // the finder is explicitly "dars YOKI event qo'shish", so
                    // unlike a plain cell click it keeps the purpose choice
                },
            },
            { onClose: () => this.load() }
        );
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
