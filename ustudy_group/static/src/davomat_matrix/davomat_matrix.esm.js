/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class DavomatMatrix extends Component {
    static template = "ustudy_group.DavomatMatrix";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, data: null, moduleIndex: 0 });
        this.groupId =
            (this.props.action && this.props.action.params && this.props.action.params.group_id) ||
            (this.props.action && this.props.action.context && this.props.action.context.group_id) ||
            false;
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const data = await this.orm.call("edu.davomat.matrix", "get_matrix_data", [this.groupId]);
        this.state.data = data;
        const idx = data.modules.findIndex((m) => m.seq === data.current_seq);
        this.state.moduleIndex = idx >= 0 ? idx : 0;
        this.state.loading = false;
    }

    get currentModule() {
        const modules = this.state.data ? this.state.data.modules : [];
        return modules[this.state.moduleIndex] || null;
    }

    get today() {
        return (this.state.data && this.state.data.today) || { has_lesson: false };
    }

    async startLesson() {
        // Opens the start-photo camera wizard; on close the board reloads and
        // shows the in-progress selectors.
        const action = await this.orm.call(
            "edu.davomat.matrix", "matrix_start_lesson", [this.groupId]
        );
        this.action.doAction(action, { onClose: () => this.load() });
    }

    async finishLesson() {
        // Opens homework wizard → end-photo camera wizard → confirm (server
        // chained). Reload once the whole chain closes.
        const action = await this.orm.call(
            "edu.davomat.matrix", "matrix_finish_lesson", [this.groupId]
        );
        this.action.doAction(action, { onClose: () => this.load() });
    }

    async setStatus(studentId, ev) {
        const status = ev.target.value;
        const attId = this.today.attendance_id;
        if (!attId) {
            return;
        }
        await this.orm.call(
            "edu.davomat.matrix", "matrix_set_status", [attId, studentId, status]
        );
        const student = this.state.data.students.find((s) => s.student_id === studentId);
        if (student) {
            student.today_status = status;
        }
    }

    shiftModule(direction) {
        const count = this.state.data ? this.state.data.modules.length : 0;
        const next = this.state.moduleIndex + direction;
        if (next >= 0 && next < count) {
            this.state.moduleIndex = next;
        }
    }

    openGroup() {
        if (!this.groupId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "edu.group",
            res_id: this.groupId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("ustudy_group.davomat_matrix", DavomatMatrix);
