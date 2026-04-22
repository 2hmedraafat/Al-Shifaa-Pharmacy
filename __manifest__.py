{
    'name': 'Pharmacy',
    'version': '18.0.1.0.0',
    'category': 'Pharmacy',
    'depends': ['product', 'stock', 'point_of_sale', 'mail'],
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