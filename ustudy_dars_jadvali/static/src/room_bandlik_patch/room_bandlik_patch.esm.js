/** @odoo-module **/

import {patch} from "@web/core/utils/patch";
import {deserializeDateTime, serializeDateTime} from "@web/core/l10n/dates";
import {RoomBandlikController} from "@ustudy_group/room_bandlik/room_bandlik_controller.esm";
import {RoomBandlikModel} from "@ustudy_group/room_bandlik/room_bandlik_model.esm";

const PURPOSE_LABELS = {
    majlis: "Majlis",
    konsultatsiya: "Konsultatsiya",
    mehmon: "Mehmon uchun",
};

// Xonalar bandligi gets the SAME "Xonani band qilish" wizard as the Jadval
// doskasi board — with the full purpose choice (dars/majlis/konsultatsiya/
// mehmon) and weekly repeat. The board itself passes default_dars_only and
// only adds lessons; this page is where non-dars bookings are made.
patch(RoomBandlikController.prototype, {
    async onAdd(roomId, day) {
        this.env.services.action.doAction(
            {
                type: "ir.actions.act_window",
                name: "Xonani band qilish",
                res_model: "dars.jadvali.add.lesson.wizard",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_room_id: roomId,
                    default_lesson_date: day.toISODate(),
                    default_start_time: 9,
                    default_end_time: 10.5,
                },
            },
            {onClose: () => this._reload()}
        );
    },

    onOpen(lessonId) {
        // booking cards carry key "b<id>": open the booking record instead
        // of an edu.timetable form
        if (typeof lessonId === "string" && lessonId.startsWith("b")) {
            this.env.services.action.doAction(
                {
                    type: "ir.actions.act_window",
                    name: "Xona bandi",
                    res_model: "dars.jadvali.booking",
                    res_id: parseInt(lessonId.slice(1)),
                    views: [[false, "form"]],
                    target: "new",
                },
                {onClose: () => this._reload()}
            );
            return;
        }
        super.onOpen(lessonId);
    },
});

// Non-lesson bookings share the grid, exactly like on the board: fetched for
// the shown week and merged into the same cells with their own styling.
patch(RoomBandlikModel.prototype, {
    async _fetch() {
        try {
            this._bookings = await this.orm.searchRead(
                "dars.jadvali.booking",
                [
                    ["start_datetime", "<", serializeDateTime(this.weekEnd)],
                    ["end_datetime", ">", serializeDateTime(this.weekStart)],
                ],
                ["purpose", "room_id", "start_datetime", "end_datetime", "note"]
            );
        } catch {
            // module data not reachable (e.g. no access): grid still works
            this._bookings = [];
        }
        return super._fetch();
    },

    _buildGrid(lessons, rooms) {
        super._buildGrid(lessons, rooms);
        for (const bk of this._bookings || []) {
            if (!bk.room_id) {
                continue;
            }
            const start = deserializeDateTime(bk.start_datetime);
            const stop = bk.end_datetime ? deserializeDateTime(bk.end_datetime) : null;
            const key = this.cellKey(bk.room_id[0], start.toISODate());
            if (!(key in this.cells)) {
                continue;
            }
            this.cells[key].push({
                id: "b" + bk.id,
                start,
                stop,
                time:
                    start.toFormat("HH:mm") +
                    (stop ? `–${stop.toFormat("HH:mm")}` : ""),
                group: PURPOSE_LABELS[bk.purpose] || bk.purpose,
                teacher: bk.note || "",
                state: "booking",
                stateClass: "o_rb_booking",
            });
            this.cells[key].sort((a, b) => a.start - b.start);
        }
    },
});
