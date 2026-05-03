/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { patch } from "@web/core/utils/patch";



function pharmacyGetSaleableQty(product) {
    const rawQty = product?.pharmacy_saleable_qty ?? product?.raw?.pharmacy_saleable_qty;
    if (rawQty === undefined || rawQty === null || rawQty === "") {
        return null;
    }
    const qty = Number(rawQty);
    return Number.isFinite(qty) ? qty : null;
}

function pharmacyGetProductId(product) {
    return product?.id ?? product?.raw?.id ?? false;
}

function pharmacyGetProductDisplayName(product) {
    return product?.display_name || product?.name || product?.raw?.display_name || product?.raw?.name || _t("this product");
}

function pharmacyOrderProductQty(order, product, excludeLine = null) {
    const productId = pharmacyGetProductId(product);
    if (!order || !productId) {
        return 0;
    }
    const lines = Array.from(order.get_orderlines?.() || order.lines || []);
    return lines.reduce((total, line) => {
        if (excludeLine && line === excludeLine) {
            return total;
        }
        const lineProduct = line.get_product?.() || line.product_id || line.product;
        if (pharmacyGetProductId(lineProduct) !== productId) {
            return total;
        }
        const qty = line.get_quantity?.() ?? line.qty ?? line.quantity ?? 0;
        return total + Number(qty || 0);
    }, 0);
}

function pharmacyBuildStockWarning(product, saleableQty) {
    return {
        title: _t("Not Enough Saleable Stock"),
        body: _t(
            "You cannot sell more than %(qty)s unit(s) of %(product)s. Expired-location stock is excluded for patient safety.",
            {
                qty: saleableQty,
                product: pharmacyGetProductDisplayName(product),
            }
        ),
    };
}

// Central POS safety layer: blocks product card, barcode, suggestions, and every add-line flow.
// Odoo 18 sometimes calls addLineToOrder() directly, so the gate must be here,
// not only in ProductScreen.addProductToOrder().
patch(PosStore.prototype, {
    async _pharmacyEnsureSaleableQty(product) {
        let saleableQty = pharmacyGetSaleableQty(product);
        if (saleableQty !== null || !product?.id) {
            return saleableQty;
        }

        // Fallback for already-open POS sessions / cached products that were loaded
        // before the new field was added to the POS loader.
        const rows = await this.data.searchRead(
            "product.product",
            [["id", "=", product.id]],
            ["pharmacy_saleable_qty"],
            { limit: 1 }
        );
        saleableQty = Number(rows?.[0]?.pharmacy_saleable_qty ?? 0);
        if (!Number.isFinite(saleableQty)) {
            saleableQty = 0;
        }
        product.pharmacy_saleable_qty = saleableQty;
        if (product.raw) {
            product.raw.pharmacy_saleable_qty = saleableQty;
        }
        return saleableQty;
    },

    async addLineToOrder(vals, order, opts = {}, configure = true) {
        const product = typeof vals?.product_id === "number"
            ? this.data.models["product.product"].get(vals.product_id)
            : vals?.product_id;

        if (product) {
            const saleableQty = await this._pharmacyEnsureSaleableQty(product);
            const existingQty = pharmacyOrderProductQty(order || this.get_order?.(), product);
            const requestedQty = Number(vals?.qty ?? opts?.quantity ?? 1);
            const nextQty = existingQty + requestedQty;
            if (requestedQty > 0 && (saleableQty <= 0 || nextQty > saleableQty)) {
                this.dialog.add(AlertDialog, pharmacyBuildStockWarning(product, saleableQty));
                return false;
            }
        }
        return await super.addLineToOrder(vals, order, opts, configure);
    },
});

// Hard safety layer: caps direct quantity edits from the Qty numpad.
// This prevents bypassing by selecting the order line then typing 26, 99, etc.
patch(PosOrderline.prototype, {
    set_quantity(quantity, keep_price) {
        const product = this.get_product?.() || this.product_id;
        const saleableQty = pharmacyGetSaleableQty(product);
        if (saleableQty !== null) {
            const requestedQty = Number(quantity || 0);
            if (requestedQty > 0) {
                const order = this.order_id;
                const otherQty = pharmacyOrderProductQty(order, product, this);
                const maxForThisLine = Math.max(saleableQty - otherQty, 0);
                if (requestedQty > maxForThisLine) {
                    const result = super.set_quantity(maxForThisLine, keep_price);
                    return pharmacyBuildStockWarning(product, saleableQty) || result;
                }
            }
        }
        return super.set_quantity(quantity, keep_price);
    },
});

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
        const saleableQty = this._pharmacyGetSaleableQty(product);

        if (saleableQty !== null && saleableQty <= 0) {
            this.dialog.add(AlertDialog, {
                title: _t("Expired / Not Saleable"),
                body: _t("This product has no saleable quantity. Expired-location stock is excluded from POS for patient safety."),
            });
            return false;
        }

        // Patient safety: do not allow POS to add more than the quantity available
        // in normal internal locations. Stock moved to Expired Medicines is ignored.
        const currentProductQty = this._pharmacyGetProductOrderQuantity(product);
        const nextProductQty = currentProductQty + 1;
        if (saleableQty !== null && nextProductQty > saleableQty) {
            this.dialog.add(AlertDialog, {
                title: _t("Not Enough Saleable Stock"),
                body: _t(
                    "You cannot sell more than %(qty)s unit(s) of %(product)s. Expired-location stock is excluded for patient safety.",
                    {
                        qty: saleableQty,
                        product: this._pharmacyGetProductDisplayName(product),
                    }
                ),
            });
            return false;
        }

        const beforeQty = this._pharmacyGetOrderTotalQuantity();
        const result = await super.addProductToOrder(product);
        const afterQty = this._pharmacyGetOrderTotalQuantity();

        if (!this._pharmacySuppressSuggestionPopup && afterQty > beforeQty) {
            await this._pharmacyShowProductSuggestions(product);
        }

        return result;
    },



    async updateSelectedOrderline(...args) {
        // Patient safety: the numpad Qty button can change the selected line directly.
        // This check prevents bypassing the addProductToOrder stock limit.
        if (this._pharmacyShouldBlockNumpadQuantityChange(args)) {
            return false;
        }
        return await super.updateSelectedOrderline(...args);
    },

    _pharmacyShouldBlockNumpadQuantityChange(args) {
        const order = this.pos.get_order?.() || this.currentOrder;
        const selectedLine = order?.get_selected_orderline?.() || order?.getSelectedOrderline?.() || order?.selected_orderline;
        if (!selectedLine) {
            return false;
        }

        const mode = this.pos.numpadMode || this.numpadMode || this.numberBuffer?.mode || this.state?.numpadMode;
        const payload = args?.[0] || {};
        const key = payload.key ?? payload.buttonValue ?? payload.value ?? payload;
        const buffer = payload.buffer ?? this.numberBuffer?.get?.() ?? this.numberBuffer?.state?.buffer;

        // Only block explicit quantity changes. Price/discount buttons must keep working.
        if (mode && mode !== "quantity" && key !== "quantity") {
            return false;
        }

        const lineProduct = selectedLine.get_product?.() || selectedLine.product || selectedLine.product_id;
        const saleableQty = this._pharmacyGetSaleableQty(lineProduct);
        if (saleableQty === null) {
            return false;
        }

        const currentLineQty = Number(selectedLine.get_quantity?.() ?? selectedLine.qty ?? selectedLine.quantity ?? 0);
        let newLineQty = this._pharmacyParseNumpadQuantity(buffer, key, currentLineQty);
        if (newLineQty === null) {
            return false;
        }
        newLineQty = Math.max(newLineQty, 0);

        const productId = this._pharmacyGetProductId(lineProduct);
        const rawLines = order?.get_orderlines?.() || order?.lines || [];
        const lines = Array.from(rawLines);
        const otherQty = lines.reduce((total, line) => {
            if (line === selectedLine) {
                return total;
            }
            const product = line.get_product?.() || line.product || line.product_id;
            if (this._pharmacyGetProductId(product) !== productId) {
                return total;
            }
            const qty = line.get_quantity?.() ?? line.qty ?? line.quantity ?? 0;
            return total + Number(qty || 0);
        }, 0);

        const finalQty = otherQty + newLineQty;
        if (finalQty > saleableQty) {
            this.dialog.add(AlertDialog, {
                title: _t("Not Enough Saleable Stock"),
                body: _t(
                    "You cannot sell more than %(qty)s unit(s) of %(product)s. Expired-location stock is excluded for patient safety.",
                    {
                        qty: saleableQty,
                        product: this._pharmacyGetProductDisplayName(lineProduct),
                    }
                ),
            });
            return true;
        }
        return false;
    },

    _pharmacyParseNumpadQuantity(buffer, key, currentQty) {
        if (key === "Backspace") {
            const currentText = String(buffer ?? currentQty ?? "");
            const nextText = currentText.slice(0, -1);
            return nextText ? Number(nextText) : 0;
        }
        if (key === "Delete" || key === "CLEAR" || key === "Clear") {
            return 0;
        }
        if (typeof buffer === "string" && buffer !== "") {
            const qty = Number(buffer);
            return Number.isFinite(qty) ? qty : null;
        }
        if (typeof key === "number") {
            return key;
        }
        if (typeof key === "string" && /^\d+(\.\d+)?$/.test(key)) {
            const base = String(currentQty || "");
            const qty = Number(base === "0" ? key : base + key);
            return Number.isFinite(qty) ? qty : null;
        }
        return null;
    },

    _pharmacyHasSaleableQty(product) {
        const qty = product?.pharmacy_saleable_qty ?? product?.raw?.pharmacy_saleable_qty;
        return qty === undefined || qty === null || Number(qty) > 0;
    },

    _pharmacyGetSaleableQty(product) {
        const rawQty = product?.pharmacy_saleable_qty ?? product?.raw?.pharmacy_saleable_qty;
        if (rawQty === undefined || rawQty === null || rawQty === "") {
            return null;
        }
        const qty = Number(rawQty);
        return Number.isFinite(qty) ? qty : null;
    },

    _pharmacyGetProductId(product) {
        return product?.id ?? product?.raw?.id ?? false;
    },

    _pharmacyGetProductDisplayName(product) {
        return product?.display_name || product?.name || product?.raw?.display_name || product?.raw?.name || _t("this product");
    },

    _pharmacyGetProductOrderQuantity(product) {
        const productId = this._pharmacyGetProductId(product);
        if (!productId) {
            return 0;
        }

        const order = this.pos.get_order?.() || this.currentOrder;
        const rawLines = order?.get_orderlines?.() || order?.lines || [];
        const lines = Array.from(rawLines);
        return lines.reduce((total, line) => {
            const lineProduct = line.get_product?.() || line.product || line.product_id;
            const lineProductId = this._pharmacyGetProductId(lineProduct);
            if (lineProductId !== productId) {
                return total;
            }
            const qty = line.get_quantity?.() ?? line.qty ?? line.quantity ?? 0;
            return total + Number(qty || 0);
        }, 0);
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
            ["id", "display_name", "lst_price", "product_tmpl_id", "pharmacy_saleable_qty"],
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
                const saleableProduct = this._pharmacyHasSaleableQty(suggestedProduct) && this._pharmacyHasSaleableQty(loadedProduct);
                return {
                    id: line.id,
                    type_label: line.suggestion_type === "similar" ? _t("Similar Alternative") : _t("Complementary Product"),
                    product_id: suggestedProduct.id,
                    product_name: suggestedProduct.display_name,
                    price: suggestedProduct.lst_price,
                    note: line.note || "",
                    available: !!loadedProduct && saleableProduct,
                    unavailable_reason: !loadedProduct
                        ? _t("Refresh POS to load this product")
                        : (!saleableProduct ? _t("No saleable stock. Expired stock is excluded") : ""),
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
