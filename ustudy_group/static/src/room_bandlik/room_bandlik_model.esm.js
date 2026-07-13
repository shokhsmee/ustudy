/** @odoo-module **/

import {Model} from "@web/model/model";
import {KeepLast} from "@web/core/utils/concurrency";
import {deserializeDateTime, serializeDateTime} from "@web/core/l10n/dates";

const {DateTime} = luxon;

const STATE_CLASS = {
    scheduled: "o_rb_scheduled",
    in_progress: "o_rb_in_progress",
    completed: "o_rb_completed",
    cancelled: "o_rb_cancelled",
};

export class RoomBandlikModel extends Model {
    setup(params) {
        this.resModel = params.resModel;
        this.fields = params.fields;
        this.archInfo = params.archInfo;
        this.fieldNames = params.archInfo.fieldNames;
        this.keepLast = new KeepLast();

        // Week currently shown; navigation moves it by ±1 week.
        this.focusDate = DateTime.local().startOf("day");
        this.searchParams = {domain: [], context: {}};
        this.rooms = [];
        this.days = [];
        this.cells = {};
    }

    get weekStart() {
        return this.focusDate.startOf("week");
    }

    get weekEnd() {
        return this.weekStart.plus({weeks: 1});
    }

    get weekLabel() {
        const start = this.weekStart;
        const end = this.weekStart.plus({days: 6});
        return `${start.toFormat("dd MMM")} – ${end.toFormat("dd MMM yyyy")}`;
    }

    cellKey(roomId, isoDate) {
        return `${roomId}|${isoDate}`;
    }

    async load(searchParams) {
        this.searchParams = searchParams;
        await this._fetch();
    }

    setWeek(delta) {
        this.focusDate = this.focusDate.plus({weeks: delta});
        return this._fetch();
    }

    today() {
        this.focusDate = DateTime.local().startOf("day");
        return this._fetch();
    }

    async _fetch() {
        const {date_start, room_field} = this.archInfo;
        const domain = [
            ...(this.searchParams.domain || []),
            [date_start, ">=", serializeDateTime(this.weekStart)],
            [date_start, "<", serializeDateTime(this.weekEnd)],
        ];
        const [lessons, rooms] = await this.keepLast.add(
            Promise.all([
                this.orm.searchRead(this.resModel, domain, this.fieldNames, {
                    context: this.searchParams.context,
                    order: `${room_field}, ${date_start}`,
                }),
                this.orm.searchRead("edu.room", [], ["id", "name"], {
                    order: "sequence, name",
                }),
            ])
        );
        this._buildGrid(lessons, rooms);
        this.notify();
    }

    _buildGrid(lessons, rooms) {
        this.rooms = rooms;
        this.days = Array.from({length: 7}, (_, i) =>
            this.weekStart.plus({days: i})
        );

        const cells = {};
        for (const room of rooms) {
            for (const day of this.days) {
                cells[this.cellKey(room.id, day.toISODate())] = [];
            }
        }

        const {
            date_start,
            date_stop,
            room_field,
            group_field,
            teacher_field,
            state_field,
        } = this.archInfo;

        for (const rec of lessons) {
            const room = rec[room_field];
            if (!room) {
                continue;
            }
            const start = deserializeDateTime(rec[date_start]);
            const stop = rec[date_stop] ? deserializeDateTime(rec[date_stop]) : null;
            const key = this.cellKey(room[0], start.toISODate());
            if (!(key in cells)) {
                continue;
            }
            const group = rec[group_field];
            const teacher = rec[teacher_field];
            cells[key].push({
                id: rec.id,
                start,
                stop,
                time:
                    start.toFormat("HH:mm") +
                    (stop ? `–${stop.toFormat("HH:mm")}` : ""),
                group: group ? group[1] : "",
                teacher: teacher ? teacher[1] : "",
                state: rec[state_field],
                stateClass: STATE_CLASS[rec[state_field]] || "",
            });
        }
        for (const key of Object.keys(cells)) {
            cells[key].sort((a, b) => a.start - b.start);
        }
        this.cells = cells;
    }
}
