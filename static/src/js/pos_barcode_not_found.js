/** @odoo-module **/

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

patch(ProductScreen.prototype, {
    async _barcodeProductAction(code) {
        const product = this.pos.db.get_product_by_barcode(code.base_code);
        if (product) {
            return await super._barcodeProductAction(...arguments);
        }

        this.dialog.add(AlertDialog, {
            title: "Barcode Not Found",
            body: `No product found for barcode: ${code.base_code}`,
        });

        return false;
    },
});