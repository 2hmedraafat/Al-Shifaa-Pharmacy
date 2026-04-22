import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { _t } from "@web/core/l10n/translation";

patch(PosStore.prototype, {

    async _barcodeErrorAction(code) {
        const { confirmed, payload } = await this.env.services.dialog.add(
            BarcodeNotFoundDialog,
            { barcode: code.base_code }
        );

        if (!confirmed) return;

        if (payload === 'new') {
            this.env.services.action.doAction({
                type: 'ir.actions.act_window',
                res_model: 'product.template',
                views: [[false, 'form']],
                target: 'new',
                context: { default_barcode: code.base_code },
            });
        } else if (payload === 'link') {
            this.env.services.action.doAction({
                type: 'ir.actions.act_window',
                res_model: 'product.template',
                views: [[false, 'list']],
                target: 'new',
                context: { default_barcode: code.base_code },
            });
        }
    }
});


import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

export class BarcodeNotFoundDialog extends Component {
    static template = "pharmacy.BarcodeNotFoundDialog";
    static props = {
        barcode: String,
        close: Function,
    };

    setup() {
        this.dialogService = useService("dialog");
    }

    onCreateNew() {
        this.props.close({ confirmed: true, payload: 'new' });
    }

    onLinkExisting() {
        this.props.close({ confirmed: true, payload: 'link' });
    }

    onCancel() {
        this.props.close({ confirmed: false });
    }
}