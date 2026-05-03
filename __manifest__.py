{
    'name': 'Pharmacy',
    'version': '18.0.1.0.0',
    'category': 'Pharmacy',
    'license': 'LGPL-3',
    'depends': ['product', 'stock', 'product_expiry', 'point_of_sale', 'mail', 'sale_management', 'purchase', 'account'],
    'data': [
        'security/pharmacy_groups.xml',
        'security/ir.model.access.csv',

        'data/pharmacy_sequence.xml',
        'data/uom_data.xml',
        'data/stock_data.xml',
        'data/expiry_alert_cron.xml',
        'data/expired_location_data.xml',

        'views/product_template_views.xml',
        'views/res_config_settings_views.xml',
        'views/pharmacy_prescription_views.xml',
        'views/pharmacy_register_views.xml',
        'views/product_views.xml',
        'views/sale_views.xml',
        'views/product_search_views.xml',
        'views/purchase_order_views.xml',
        'views/commission_report_views.xml',
        'views/stock_lot_expiry_views.xml',
        'views/stock_location_views.xml',

        'wizard/bulk_price_update_wizard_views.xml',
        'wizard/scheduled_medicine_sale_confirm_views.xml',
        'wizard/sale_product_suggestion_wizard_views.xml',
        'wizard/expired_medicines_report_wizard_views.xml',

        'report/product_classification_report.xml',
        'report/product_classification_report_template.xml',
        'report/expired_medicines_report_views.xml',

        'views/menus.xml',
        'views/pharmacy_expiry_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'pharmacy/static/src/js/month_year_expiry_widget.js',
            'pharmacy/static/src/xml/month_year_expiry_widget.xml',
        ],
        'point_of_sale._assets_pos': [
            'pharmacy/static/src/js/pos_pharmacist_auth.js',
            'pharmacy/static/src/css/pos_expiry_indicator.css',
            'pharmacy/static/src/js/pos_barcode_not_found.js',
            'pharmacy/static/src/js/pos_product_suggestions.js',
            'pharmacy/static/src/xml/pos_pharmacist_auth.xml',
            'pharmacy/static/src/xml/pos_expiry_indicator.xml',
            'pharmacy/static/src/xml/pos_barcode_not_found.xml',
            'pharmacy/static/src/xml/pos_product_suggestions.xml',
        ],
    },
    'installable': True,
    'application': True,
}
