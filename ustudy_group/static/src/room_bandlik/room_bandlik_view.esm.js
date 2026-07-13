/** @odoo-module **/

import {registry} from "@web/core/registry";
import {_t} from "@web/core/l10n/translation";
import {RoomBandlikArchParser} from "./room_bandlik_arch_parser.esm";
import {RoomBandlikController} from "./room_bandlik_controller.esm";
import {RoomBandlikModel} from "./room_bandlik_model.esm";

export const RoomBandlikView = {
    type: "room_bandlik",
    display_name: _t("Xonalar bandligi"),
    icon: "fa fa-th",
    multiRecord: true,
    Controller: RoomBandlikController,
    ArchParser: RoomBandlikArchParser,
    Model: RoomBandlikModel,

    props: (genericProps, view) => {
        const {arch, fields, resModel} = genericProps;
        const archInfo = new view.ArchParser().parse(arch, fields);
        return {
            ...genericProps,
            Model: view.Model,
            modelParams: {
                resModel,
                fields,
                archInfo,
            },
        };
    },
};

registry.category("views").add("room_bandlik", RoomBandlikView);
