{
    'name': 'Warehouse-Scoped User Security',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Restrict a user to specific warehouses',
    'author': 'AlShayeb Partners',
    'license': 'OPL-1',
    # stock, and nothing else. This is Odoo authorisation, not an AI concern:
    # it must not depend on ai_operations, and ai_operations must not depend on
    # it. Warehouse restriction reaches the AI guard the ordinary way, through
    # the execution user's own record rules.
    'depends': ['stock'],
    'data': [
        'security/stock_security_warehouse_groups.xml',
        'security/stock_security_warehouse_rules.xml',
        'views/res_users_views.xml',
    ],
    'installable': True,
    'application': False,
}
