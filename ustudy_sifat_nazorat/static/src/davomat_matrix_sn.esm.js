/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { DavomatMatrix } from "@ustudy_group/davomat_matrix/davomat_matrix.esm";

patch(DavomatMatrix.prototype, {
    /**
     * Open the Sababli/Sababsiz wizard for one student's absence and reload
     * the board when it closes (so the green outline/medkit icon shows up).
     */
    async openReasonWizard(timetableId, studentId) {
        const action = await this.orm.call(
            "edu.davomat.matrix",
            "matrix_open_reason_wizard",
            [timetableId, studentId]
        );
        this.action.doAction(action, { onClose: () => this.load() });
    },
});
