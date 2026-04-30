/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

class PharmacyProductSuggestionsDialog extends Component {
    static template = "pharmacy.ProductSuggestionsDialog";
    static components = { Dialog };
    static props = {
        productName: String,
        suggestions: Array,
        addSuggestedProducts: Function,
        close: Function,
        onClose: { type: Function, optional: true },
    };

    setup() {
        this.state = useState({
            suggestions: this.props.suggestions.map((suggestion) => ({
                ...suggestion,
                selected: suggestion.available,
            })),
        });
    }

    toggleSuggestion(suggestion, ev) {
        if (!suggestion.available) {
            ev.preventDefault();
            return;
        }
        suggestion.selected = ev.target.checked;
    }

    closeDialog() {
        this.props.onClose?.();
        this.props.close();
    }

    async addSelected() {
        const selectedProductIds = this.state.suggestions
            .filter((suggestion) => suggestion.selected && suggestion.available)
            .map((suggestion) => suggestion.product_id);

        const added = await this.props.addSuggestedProducts(selectedProductIds);
        if (added) {
            this.closeDialog();
        }
    }
}

patch(ProductScreen.prototype, {
    async addProductToOrder(product) {
        const beforeQty = this._pharmacyGetOrderTotalQuantity();
        const result = await super.addProductToOrder(product);
        const afterQty = this._pharmacyGetOrderTotalQuantity();

        if (!this._pharmacySuppressSuggestionPopup && afterQty > beforeQty) {
            await this._pharmacyShowProductSuggestions(product);
        }

        return result;
    },

    _pharmacyGetOrderTotalQuantity() {
        const order = this.pos.get_order?.() || this.currentOrder;
        const rawLines = order?.get_orderlines?.() || order?.lines || [];
        const lines = Array.from(rawLines);
        return lines.reduce((total, line) => {
            const qty = line.get_quantity?.() ?? line.qty ?? line.quantity ?? 0;
            return total + Number(qty || 0);
        }, 0);
    },

    async _pharmacyShowProductSuggestions(product) {
        if (!product || this._pharmacySuggestionDialogOpen) {
            return;
        }

        const productTemplateId = await this._pharmacyGetProductTemplateId(product);
        if (!productTemplateId) {
            return;
        }

        const suggestionLines = await this.pos.data.searchRead(
            "pharmacy.product.suggestion",
            [["product_tmpl_id", "=", productTemplateId], ["active", "=", true]],
            ["suggestion_type", "suggested_product_tmpl_id", "note"],
            { limit: 20 }
        );

        if (!suggestionLines.length) {
            return;
        }

        const suggestedTemplateIds = suggestionLines
            .map((line) => this._pharmacyMany2OneId(line.suggested_product_tmpl_id))
            .filter(Boolean);

        if (!suggestedTemplateIds.length) {
            return;
        }

        const suggestedProducts = await this.pos.data.searchRead(
            "product.product",
            [["product_tmpl_id", "in", suggestedTemplateIds], ["available_in_pos", "=", true]],
            ["id", "display_name", "lst_price", "product_tmpl_id"],
            { limit: 50 }
        );

        const productsByTemplate = new Map();
        for (const suggestedProduct of suggestedProducts) {
            const tmplId = this._pharmacyMany2OneId(suggestedProduct.product_tmpl_id);
            if (tmplId && !productsByTemplate.has(tmplId)) {
                productsByTemplate.set(tmplId, suggestedProduct);
            }
        }

        const suggestions = suggestionLines
            .map((line) => {
                const tmplId = this._pharmacyMany2OneId(line.suggested_product_tmpl_id);
                const suggestedProduct = productsByTemplate.get(tmplId);
                if (!suggestedProduct) {
                    return false;
                }

                const loadedProduct = this._pharmacyGetLoadedProduct(suggestedProduct.id);
                return {
                    id: line.id,
                    type_label: line.suggestion_type === "similar" ? _t("Similar Alternative") : _t("Complementary Product"),
                    product_id: suggestedProduct.id,
                    product_name: suggestedProduct.display_name,
                    price: suggestedProduct.lst_price,
                    note: line.note || "",
                    available: !!loadedProduct,
                    unavailable_reason: loadedProduct ? "" : _t("Refresh POS to load this product"),
                };
            })
            .filter(Boolean);

        if (!suggestions.length) {
            return;
        }

        this._pharmacySuggestionDialogOpen = true;
        this.dialog.add(PharmacyProductSuggestionsDialog, {
            productName: product.display_name || product.name || _t("Selected Product"),
            suggestions,
            addSuggestedProducts: (productIds) => this._pharmacyAddSuggestedProducts(productIds),
            onClose: () => {
                this._pharmacySuggestionDialogOpen = false;
            },
        });
    },

    async _pharmacyGetProductTemplateId(product) {
        const directValue =
            product.product_tmpl_id ??
            product.raw?.product_tmpl_id ??
            product.product_template_id ??
            product.raw?.product_template_id;
        const directId = this._pharmacyMany2OneId(directValue);
        if (directId) {
            return directId;
        }

        const records = await this.pos.data.searchRead(
            "product.product",
            [["id", "=", product.id]],
            ["product_tmpl_id"],
            { limit: 1 }
        );
        return this._pharmacyMany2OneId(records?.[0]?.product_tmpl_id);
    },

    _pharmacyMany2OneId(value) {
        if (Array.isArray(value)) {
            return value[0];
        }
        if (value && typeof value === "object") {
            return value.id;
        }
        return value || false;
    },

    _pharmacyGetLoadedProduct(productId) {
        return (
            this.pos.db?.get_product_by_id?.(productId) ||
            this.pos.models?.["product.product"]?.get?.(productId) ||
            this.pos.models?.["product.product"]?.find?.((product) => product.id === productId) ||
            this.pos.models?.["product.product"]?.filter?.((product) => product.id === productId)?.[0]
        );
    },

    async _pharmacyAddSuggestedProducts(productIds) {
        if (!productIds.length) {
            this.dialog.add(AlertDialog, {
                title: _t("No Product Selected"),
                body: _t("Please select at least one suggested product."),
            });
            return false;
        }

        let addedAnyProduct = false;
        this._pharmacySuppressSuggestionPopup = true;
        try {
            for (const productId of productIds) {
                const product = this._pharmacyGetLoadedProduct(productId);
                if (!product) {
                    this.dialog.add(AlertDialog, {
                        title: _t("Product Not Loaded"),
                        body: _t("One of the selected products is not loaded in this POS session. Please refresh POS."),
                    });
                    continue;
                }
                await this.addProductToOrder(product);
                addedAnyProduct = true;
            }
        } finally {
            this._pharmacySuppressSuggestionPopup = false;
        }
        return addedAnyProduct;
    },
});
