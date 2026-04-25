{
    'name': 'Pharmacy',
    'version': '18.0.1.0.0',
    'category': 'Pharmacy',
    'license': 'LGPL-3',
    'depends': ['product', 'stock', 'point_of_sale', 'mail', 'sale_management', 'purchase', 'account'],
    'data': [
        'security/pharmacy_groups.xml',
        'security/ir.model.access.csv',

        'data/pharmacy_sequence.xml',
        'data/uom_data.xml',
        'data/stock_data.xml',

        'views/product_template_views.xml',
        'views/pharmacy_prescription_views.xml',
        'views/pharmacy_register_views.xml',
        'views/product_views.xml',
        'views/sale_views.xml',
        'views/product_search_views.xml',
        'views/purchase_order_views.xml',
        'views/commission_report_views.xml',

        'views/menus.xml',

        'report/product_classification_report.xml',
        'report/product_classification_report_template.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pharmacy/static/src/js/pos_pharmacist_auth.js',
            'pharmacy/static/src/js/pos_barcode_not_found.js',
            'pharmacy/static/src/xml/pos_pharmacist_auth.xml',
            'pharmacy/static/src/xml/pos_barcode_not_found.xml',
        ],
    },
    'installable': True,
    'application': True,
}