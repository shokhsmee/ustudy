/** @odoo-module **/

import {visitXML} from "@web/core/utils/xml";

/**
 * Parser for the <room_bandlik> arch. Keeps it intentionally small: we only
 * need the start/stop datetime fields, the room (grouping) field and any extra
 * <field> names to read for each lesson block.
 */
export class RoomBandlikArchParser {
    parse(arch) {
        const archInfo = {
            date_start: "start_datetime",
            date_stop: "end_datetime",
            room_field: "room_id",
            group_field: "group_id",
            teacher_field: "teacher_id",
            state_field: "state",
            fieldNames: [],
        };
        visitXML(arch, (node) => {
            if (node.tagName === "room_bandlik") {
                for (const attr of [
                    "date_start",
                    "date_stop",
                    "room_field",
                    "group_field",
                    "teacher_field",
                    "state_field",
                ]) {
                    if (node.hasAttribute(attr)) {
                        archInfo[attr] = node.getAttribute(attr);
                    }
                }
            } else if (node.tagName === "field") {
                const name = node.getAttribute("name");
                if (name && !archInfo.fieldNames.includes(name)) {
                    archInfo.fieldNames.push(name);
                }
            }
        });

        // Always read the structural fields.
        for (const f of [
            archInfo.date_start,
            archInfo.date_stop,
            archInfo.room_field,
            archInfo.group_field,
            archInfo.teacher_field,
            archInfo.state_field,
        ]) {
            if (f && !archInfo.fieldNames.includes(f)) {
                archInfo.fieldNames.push(f);
            }
        }
        return archInfo;
    }
}
