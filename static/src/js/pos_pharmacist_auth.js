/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";

patch(ProductScreen.prototype, {
    async addProductToOrder(product) {
        let isScheduled =
            product?.is_scheduled_medicine ??
            product?.raw?.is_scheduled_medicine;

        if (typeof isScheduled === "undefined") {
            const records = await this.pos.data.searchRead(
                "product.product",
                [["id", "=", product.id]],
                ["is_scheduled_medicine"]
            );
            isScheduled = !!records?.[0]?.is_scheduled_medicine;
        }

        if (isScheduled) {
            const confirmed = await new Promise((resolve) => {
                this.dialog.add(ConfirmationDialog, {
                    title: _t("Scheduled Medicine!"),
                    body: _t("Pharmacist Authentication Required"),
                    confirmLabel: _t("Confirm"),
                    cancelLabel: _t("Cancel"),
                    confirm: () => resolve(true),
                    cancel: () => resolve(false),
                });
            });

            if (!confirmed) {
                return;
            }
        }

        return await super.addProductToOrder(product);
    },
});