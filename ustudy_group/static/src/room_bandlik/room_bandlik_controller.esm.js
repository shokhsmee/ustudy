/** @odoo-module **/

import {Component, useRef} from "@odoo/owl";
import {Layout} from "@web/search/layout";
import {SearchBar} from "@web/search/search_bar/search_bar";
import {FormViewDialog} from "@web/views/view_dialogs/form_view_dialog";
import {standardViewProps} from "@web/views/standard_view_props";
import {useModelWithSampleData} from "@web/model/model";
import {useSearchBarToggler} from "@web/search/search_bar/search_bar_toggler";
import {useService} from "@web/core/utils/hooks";
import {useSetupAction} from "@web/search/action_hook";
import {serializeDateTime} from "@web/core/l10n/dates";
import {RoomBandlikRenderer} from "./room_bandlik_renderer.esm";

export class RoomBandlikController extends Component {
    static template = "ustudy_group.RoomBandlikView";
    static components = {Layout, SearchBar, RoomBandlikRenderer};
    static props = {...standardViewProps, Model: Function, modelParams: Object};

    setup() {
        this.rootRef = useRef("root");
        this.model = useModelWithSampleData(this.props.Model, this.props.modelParams);
        useSetupAction({rootRef: this.rootRef});
        this.searchBarToggler = useSearchBarToggler();
        this.dialog = useService("dialog");
        this.orm = useService("orm");
    }

    get rendererProps() {
        return {
            model: this.model,
            onAdd: this.onAdd.bind(this),
            onOpen: this.onOpen.bind(this),
        };
    }

    prevWeek() {
        this.model.setWeek(-1);
    }

    nextWeek() {
        this.model.setWeek(1);
    }

    today() {
        this.model.today();
    }

    _reload() {
        this.model.load(this.model.searchParams);
    }

    /**
     * Schedule a new lesson in the given room/day. Pre-fills room, weekday and
     * a default time slot; the user picks the group and adjusts the time.
     */
    async onAdd(roomId, day) {
        const weekday = await this.orm.search(
            "edu.weekday",
            [["sequence", "=", day.weekday]],
            {limit: 1}
        );
        const start = day.set({hour: 9, minute: 0, second: 0, millisecond: 0});
        const end = start.plus({hours: 1, minutes: 30});
        const context = {
            default_room_id: roomId,
            default_start_datetime: serializeDateTime(start),
            default_end_datetime: serializeDateTime(end),
        };
        if (weekday.length) {
            context.default_weekday_id = weekday[0];
        }
        this.dialog.add(FormViewDialog, {
            resModel: this.model.resModel,
            title: "Yangi dars rejalashtirish",
            context,
            onRecordSaved: () => this._reload(),
        });
    }

    onOpen(lessonId) {
        this.dialog.add(FormViewDialog, {
            resModel: this.model.resModel,
            resId: lessonId,
            title: "Dars",
            onRecordSaved: () => this._reload(),
        });
    }
}
