/** @odoo-module **/

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

class PharmacySharedBarcodeProductDialog extends Component {
    static template = "pharmacy.SharedBarcodeProductDialog";
    static components = { Dialog };
    static props = {
        barcode: String,
        products: Array,
        selectProduct: Function,
        close: Function,
    };

    onSelect(product) {
        this.props.selectProduct(product);
        this.props.close();
    }
}

patch(ProductScreen.prototype, {
    async _barcodeProductAction(code) {
        const barcode = code.base_code;
        const allProducts = await this.pos.data.searchRead(
            "product.product",
            [["barcode", "=", barcode], ["available_in_pos", "=", true]],
            ["id", "display_name", "barcode", "lst_price", "is_scheduled_medicine", "pharmacy_saleable_qty"],
            { limit: 20 }
        );
        const products = allProducts.filter((product) => this._pharmacyHasSaleableQty(product));

        if (allProducts.length && !products.length) {
            this.dialog.add(AlertDialog, {
                title: _t("Expired / Not Saleable"),
                body: _t("This barcode belongs to a product that has no saleable quantity. Expired-location stock is excluded for patient safety."),
            });
            return false;
        }

        if (products.length > 1) {
            this.dialog.add(PharmacySharedBarcodeProductDialog, {
                barcode,
                products,
                selectProduct: (selectedProduct) => this._pharmacyAddProductById(selectedProduct.id),
            });
            return true;
        }

        if (products.length === 1) {
            const product = this._pharmacyGetLoadedProduct(products[0].id);
            if (product) {
                await this.addProductToOrder(product);
                return true;
            }
        }

        const product = this.pos.db?.get_product_by_barcode?.(barcode);
        if (product) {
            if (!this._pharmacyHasSaleableQty(product)) {
                this.dialog.add(AlertDialog, {
                    title: _t("Expired / Not Saleable"),
                    body: _t("This product has no saleable quantity. Expired-location stock is excluded for patient safety."),
                });
                return false;
            }
            return await super._barcodeProductAction(...arguments);
        }

        this.dialog.add(AlertDialog, {
            title: _t("Barcode Not Found"),
            body: _t("No product found for barcode: %s", barcode),
        });

        return false;
    },

    _pharmacyHasSaleableQty(product) {
        const qty = product?.pharmacy_saleable_qty ?? product?.raw?.pharmacy_saleable_qty;
        return qty === undefined || qty === null || Number(qty) > 0;
    },

    _pharmacyGetLoadedProduct(productId) {
        return (
            this.pos.db?.get_product_by_id?.(productId) ||
            this.pos.models?.["product.product"]?.get?.(productId) ||
            this.pos.models?.["product.product"]?.find?.((product) => product.id === productId) ||
            this.pos.models?.["product.product"]?.filter?.((product) => product.id === productId)?.[0]
        );
    },

    async _pharmacyAddProductById(productId) {
        const product = this._pharmacyGetLoadedProduct(productId);
        if (!product) {
            this.dialog.add(AlertDialog, {
                title: _t("Product Not Loaded"),
                body: _t("This product matches the barcode but is not loaded in the current POS session. Please refresh POS."),
            });
            return;
        }
        await this.addProductToOrder(product);
    },
});
