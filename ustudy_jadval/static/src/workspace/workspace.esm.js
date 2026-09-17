/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";

// one grid hour = 64px; the click-to-add helper and the card geometry both
// derive from it, so the constant is shared with the SCSS (--jd-hour)
const HOUR_HEIGHT = 64;
const SNAP_MINUTES = 30;

function toISO(date) {
    // local date, NOT toISOString() — that shifts the day in +05:00
    const month = `${date.getMonth() + 1}`.padStart(2, "0");
    const day = `${date.getDate()}`.padStart(2, "0");
    return `${date.getFullYear()}-${month}-${day}`;
}

function hhmm(minutes) {
    const h = `${Math.floor(minutes / 60)}`.padStart(2, "0");
    const m = `${Math.round(minutes) % 60}`.padStart(2, "0");
    return `${h}:${m}`;
}

/**
 * "Bo'sh auditoriya topish": every gap of at least the picked length in the
 * working day, grouped by day then room. Picking one opens the booking wizard
 * prefilled with it. The window list itself comes from the Jadval doskasi
 * helper, so both screens always agree on what counts as free.
 */
export class FreeRoomDialog extends Component {
    static template = "ustudy_jadval.FreeRoomDialog";
    static components = { Dialog };
    static props = {
        dateFrom: String,
        dateTo: String,
        rooms: Array,
        roomId: { type: String, optional: true },
        onPick: Function,
        close: Function,
    };

    get dialogTitle() {
        return "Bo'sh auditoriya topish";
    }

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

    pick(day, room, gap) {
        const length = parseInt(this.state.minMinutes);
        this.props.onPick({
            room_id: room.room_id,
            date: day.date,
            start_min: gap.start_min,
            end_min: Math.min(gap.start_min + length, gap.end_min),
        });
        this.props.close();
    }
}

/** Konflikt tiles drill-down: which two events hold the same room. */
export class ConflictDialog extends Component {
    static template = "ustudy_jadval.ConflictDialog";
    static components = { Dialog };
    static props = {
        conflicts: Array,
        onOpen: Function,
        close: Function,
    };

    get dialogTitle() {
        return "Konfliktlar";
    }

    open(uid) {
        this.props.onOpen(uid);
        this.props.close();
    }
}

export class JadvalWorkspace extends Component {
    static template = "ustudy_jadval.Workspace";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.hourHeight = HOUR_HEIGHT;

        this.state = useState({
            loading: true,
            data: null,
            search: "",
            filters: {
                date: toISO(new Date()),
                view: "day",
                course_id: "",
                teacher_id: "",
                room_id: "",
                type: "",
                status: "",
            },
            drawer: { open: false, loading: false, detail: null },
            // bumped every minute so the "hozir" line and clock re-render
            clockTick: 0,
        });

        this.loadedAt = Date.now();
        this.serverNowMin = 0;
        this.ticker = setInterval(() => {
            this.state.clockTick += 1;
        }, 30000);
        onWillUnmount(() => clearInterval(this.ticker));
        onWillStart(() => this.load());
    }

    // ------------------------------------------------------------------
    // data
    // ------------------------------------------------------------------
    async load() {
        this.state.loading = true;
        const f = this.state.filters;
        this.state.data = await this.orm.call("jadval.workspace", "get_workspace", [
            {
                date: f.date,
                view: f.view,
                course_id: f.course_id ? parseInt(f.course_id) : false,
                teacher_id: f.teacher_id ? parseInt(f.teacher_id) : false,
                room_id: f.room_id ? parseInt(f.room_id) : false,
                type: f.type || false,
                status: f.status || false,
            },
        ]);
        this.serverNowMin = this.state.data.now_min;
        this.loadedAt = Date.now();
        this.state.clockTick += 1;
        this.state.loading = false;
    }

    get data() {
        return this.state.data;
    }

    onFilterChange() {
        this.load();
    }

    resetFilters() {
        const f = this.state.filters;
        f.course_id = f.teacher_id = f.room_id = f.type = f.status = "";
        this.state.search = "";
        this.load();
    }

    setView(view) {
        if (this.state.filters.view === view) {
            return;
        }
        this.state.filters.view = view;
        this.load();
    }

    selectDay(day) {
        this.state.filters.date = day.date;
        this.load();
    }

    shiftWeek(direction) {
        const date = new Date(this.state.filters.date);
        date.setDate(date.getDate() + 7 * direction);
        this.state.filters.date = toISO(date);
        this.load();
    }

    goToday() {
        this.state.filters.date = toISO(new Date());
        this.load();
    }

    // ------------------------------------------------------------------
    // clock / now line
    // ------------------------------------------------------------------
    get nowMinutes() {
        // server clock (user timezone) advanced by the time spent on screen —
        // the browser's own timezone may differ from the company's
        void this.state.clockTick;
        return this.serverNowMin + (Date.now() - this.loadedAt) / 60000;
    }

    get nowLabel() {
        return hhmm(this.nowMinutes);
    }

    get showNowLine() {
        const data = this.data;
        if (!data || data.view === "rooms") {
            return false;
        }
        const inRange =
            data.view === "week"
                ? data.week.some((d) => d.date === data.today)
                : data.date === data.today;
        const minutes = this.nowMinutes;
        return (
            inRange &&
            minutes >= data.grid.start_min &&
            minutes <= data.grid.end_min
        );
    }

    get nowStyle() {
        const top = ((this.nowMinutes - this.data.grid.start_min) / 60) * HOUR_HEIGHT;
        return `top:${top}px;`;
    }

    // ------------------------------------------------------------------
    // grid geometry
    // ------------------------------------------------------------------
    get gridHeight() {
        const grid = this.data.grid;
        return ((grid.end_min - grid.start_min) / 60) * HOUR_HEIGHT;
    }

    get gridStyle() {
        return `--jd-grid-h:${this.gridHeight}px; --jd-cols:${this.data.columns.length};`;
    }

    hourStyle(hour) {
        const top = ((hour.min - this.data.grid.start_min) / 60) * HOUR_HEIGHT;
        return `top:${top}px;`;
    }

    /** Client-side text search — instant, no round trip. */
    matchesSearch(event) {
        const needle = this.state.search.trim().toLowerCase();
        if (!needle) {
            return true;
        }
        return [
            event.title,
            event.code,
            event.teacher,
            event.room_name,
            event.type_label,
            event.time_label,
        ]
            .filter(Boolean)
            .some((value) => value.toLowerCase().includes(needle));
    }

    eventsFor(column) {
        return this.data.events.filter(
            (event) => event.col === column.key && this.matchesSearch(event)
        );
    }

    eventStyle(event) {
        const grid = this.data.grid;
        const top = ((event.start_min - grid.start_min) / 60) * HOUR_HEIGHT;
        const height = Math.max(
            34,
            ((event.end_min - event.start_min) / 60) * HOUR_HEIGHT - 3
        );
        const lanes = event.lanes || 1;
        const width = 100 / lanes;
        return (
            `top:${top}px; height:${height}px;` +
            `left:calc(${event.lane * width}% + 3px);` +
            `width:calc(${width}% - 6px);`
        );
    }

    /** Mini load profile in the rail: how many events sit in each grid hour. */
    get loadBars() {
        const data = this.data;
        if (!data) {
            return [];
        }
        const day = data.view === "week" ? null : data.date;
        const hours = data.grid.hours.slice(0, -1);
        const counts = hours.map((hour) =>
            data.events.filter(
                (event) =>
                    (!day || event.date === day) &&
                    event.start_min < hour.min + 60 &&
                    event.end_min > hour.min
            ).length
        );
        const peak = Math.max(1, ...counts);
        return counts.map((count, index) => ({
            key: hours[index].min,
            height: Math.max(8, Math.round((count * 100) / peak)),
            active: count > 0,
        }));
    }

    // ------------------------------------------------------------------
    // actions
    // ------------------------------------------------------------------
    async openEvent(uid) {
        this.state.drawer.open = true;
        this.state.drawer.loading = true;
        this.state.drawer.detail = null;
        const detail = await this.orm.call("jadval.workspace", "get_event_detail", [uid]);
        this.state.drawer.detail = detail || null;
        this.state.drawer.loading = false;
    }

    closeDrawer() {
        this.state.drawer.open = false;
        this.state.drawer.detail = null;
    }

    async openDrawerRecord() {
        const detail = this.state.drawer.detail;
        if (!detail) {
            return;
        }
        if (detail.kind === "booking") {
            this.closeDrawer();
            this.action.doAction(
                {
                    type: "ir.actions.act_window",
                    name: detail.type_label,
                    res_model: "dars.jadvali.booking",
                    res_id: detail.booking_id,
                    views: [[false, "form"]],
                    target: "new",
                },
                { onClose: () => this.load() }
            );
            return;
        }
        // lessons keep the existing group popup (Reja/Fakt, o'quvchilar, …)
        const action = await this.orm.call("dars.jadvali.board", "open_lesson_wizard", [
            detail.group_id,
            detail.timetable_ids,
        ]);
        this.closeDrawer();
        this.action.doAction(action, { onClose: () => this.load() });
    }

    /** Red X in the drawer: release a non-lesson room booking. */
    deleteDrawerRecord() {
        const detail = this.state.drawer.detail;
        if (!detail || detail.kind !== "booking") {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: "Bandlikni bekor qilish",
            body: `"${detail.title}" bandligi o'chiriladi va xona bo'shatiladi. Davom etamizmi?`,
            confirmLabel: "O'chirish",
            cancelLabel: "Bekor qilish",
            confirm: async () => {
                await this.orm.unlink("dars.jadvali.booking", [detail.booking_id]);
                this.closeDrawer();
                await this.load();
            },
        });
    }

    /** Click on empty grid space -> book that exact room + time. */
    onColumnClick(column, ev) {
        if (ev.target.closest(".o_jd_event")) {
            return;
        }
        const rect = ev.currentTarget.getBoundingClientRect();
        const offset = ev.clientY - rect.top;
        const raw = this.data.grid.start_min + (offset / HOUR_HEIGHT) * 60;
        const start = Math.max(
            this.data.grid.start_min,
            Math.floor(raw / SNAP_MINUTES) * SNAP_MINUTES
        );
        this.openAddWizard({
            room_id: this.data.view === "week" ? this.state.filters.room_id : column.key,
            date: this.data.view === "week" ? column.date : this.data.date,
            start_min: start,
            end_min: Math.min(start + 90, this.data.grid.end_min),
            dars_only: true,
        });
    }

    openAddWizard(selection) {
        const context = {
            default_lesson_date: selection.date,
            default_start_time: selection.start_min / 60,
            default_end_time: selection.end_min / 60,
        };
        if (selection.room_id) {
            context.default_room_id = parseInt(selection.room_id);
        }
        if (selection.dars_only) {
            // a plain grid click adds a lesson; the header button and the free
            // room finder keep the full purpose choice (majlis/konsultatsiya/…)
            context.default_dars_only = true;
        }
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: "Xonani band qilish",
                res_model: "dars.jadvali.add.lesson.wizard",
                views: [[false, "form"]],
                target: "new",
                context,
            },
            { onClose: () => this.load() }
        );
    }

    addEvent() {
        const start = Math.max(
            this.data.grid.start_min,
            Math.min(
                Math.ceil(this.nowMinutes / SNAP_MINUTES) * SNAP_MINUTES,
                this.data.grid.end_min - 90
            )
        );
        this.openAddWizard({
            room_id: this.state.filters.room_id,
            date: this.data.date,
            start_min: start,
            end_min: start + 90,
        });
    }

    openFreeRooms() {
        const data = this.data;
        this.dialog.add(FreeRoomDialog, {
            dateFrom: data.view === "week" ? data.week[0].date : data.date,
            dateTo: data.view === "week" ? data.week[6].date : data.date,
            rooms: data.filter_options.rooms,
            roomId: this.state.filters.room_id,
            onPick: (selection) => this.openAddWizard(selection),
        });
    }

    openConflicts() {
        const conflicts = this.data ? this.data.conflicts : [];
        this.dialog.add(ConflictDialog, {
            conflicts,
            onOpen: (uid) => this.openEvent(uid),
        });
    }

    onStatClick(stat) {
        if (stat.key === "conflicts") {
            this.openConflicts();
        } else if (stat.key === "free_rooms") {
            this.openFreeRooms();
        } else if (stat.key === "busy_rooms") {
            this.setView("rooms");
        }
    }

    bookFreeWindow(room, gap) {
        this.openAddWizard({
            room_id: room.id,
            date: this.data.date,
            start_min: gap.start_min,
            end_min: Math.min(gap.start_min + 90, gap.end_min),
        });
    }
}

registry.category("actions").add("ustudy_jadval.workspace", JadvalWorkspace);
