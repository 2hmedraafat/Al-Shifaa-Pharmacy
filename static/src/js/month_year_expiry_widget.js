/** @odoo-module **/

import { Component, useState, onWillUpdateProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

class PharmacyMonthYearExpiryField extends Component {
    static template = "pharmacy.MonthYearExpiryField";
    static props = { ...standardFieldProps };

    setup() {
        this.notification = useService("notification");

        this.state = useState({
            displayValue: this._formatMonthYear(this._getValue(this.props)),
        });

        onWillUpdateProps((nextProps) => {
            this.state.displayValue = this._formatMonthYear(this._getValue(nextProps));
        });
    }

    _getValue(props = this.props) {
        return props.record?.data?.[props.name];
    }

    _getFieldType() {
        return this.props.record?.fields?.[this.props.name]?.type || "char";
    }

    _formatMonthYear(value) {
        if (!value) {
            return "";
        }

        if (typeof value === "string" && /^(0[1-9]|1[0-2])\/\d{4}$/.test(value)) {
            return value;
        }

        if (value && typeof value.toFormat === "function") {
            return value.toFormat("MM/yyyy");
        }

        if (typeof value === "string") {
            const isoMatch = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
            if (isoMatch) {
                return `${isoMatch[2]}/${isoMatch[1]}`;
            }
        }

        const dateValue = new Date(value);
        if (!Number.isNaN(dateValue.getTime())) {
            const month = String(dateValue.getMonth() + 1).padStart(2, "0");
            const year = dateValue.getFullYear();
            return `${month}/${year}`;
        }

        return "";
    }

    _getLastDayOfMonth(year, month) {
        return new Date(year, month, 0).getDate();
    }

    onInput(ev) {
        let value = ev.target.value || "";

        value = value.replace(/[^\d/]/g, "");

        if (value.length === 2 && !value.includes("/")) {
            value = value + "/";
        }

        if (value.length > 7) {
            value = value.slice(0, 7);
        }

        this.state.displayValue = value;
        ev.target.value = value;
    }

    async onChange(ev) {
        const value = (ev.target.value || "").trim();

        if (!value) {
            await this.props.record.update({ [this.props.name]: false });
            this.state.displayValue = "";
            return;
        }

        const match = value.match(/^(0[1-9]|1[0-2])\/(\d{4})$/);

        if (!match) {
            this.notification.add(
                _t("Expiry date must be in MM/YYYY format, for example 04/2026."),
                { type: "danger" }
            );

            this.state.displayValue = this._formatMonthYear(this._getValue());
            return;
        }

        const month = Number(match[1]);
        const year = Number(match[2]);
        const lastDay = this._getLastDayOfMonth(year, month);
        const fieldType = this._getFieldType();

        if (fieldType === "char") {
            await this.props.record.update({ [this.props.name]: value });
            this.state.displayValue = value;
            return;
        }

        if (fieldType === "date") {
            const dateValue = `${year}-${String(month).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`;

            await this.props.record.update({
                [this.props.name]: dateValue,
            });

            this.state.displayValue = value;
            return;
        }

        if (fieldType === "datetime") {
            const dateTimeValue = new Date(year, month - 1, lastDay, 12, 0, 0);

            await this.props.record.update({
                [this.props.name]: dateTimeValue,
            });

            this.state.displayValue = value;
            return;
        }

        await this.props.record.update({ [this.props.name]: value });
        this.state.displayValue = value;
    }
}

export const pharmacyMonthYearExpiryField = {
    component: PharmacyMonthYearExpiryField,
    supportedTypes: ["char", "date", "datetime"],
};

registry.category("fields").add("pharmacy_month_year_expiry", pharmacyMonthYearExpiryField);