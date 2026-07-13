/** @odoo-module **/

import {Component} from "@odoo/owl";

export class RoomBandlikRenderer extends Component {
    static template = "ustudy_group.RoomBandlikRenderer";
    static props = {
        model: Object,
        onAdd: Function,
        onOpen: Function,
    };

    get model() {
        return this.props.model;
    }

    cell(roomId, day) {
        return this.model.cells[this.model.cellKey(roomId, day.toISODate())] || [];
    }
}
