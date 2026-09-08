{
    'name': 'AI Operations: Inventory',
    'version': '19.0.1.3.0',
    'category': 'Productivity/AI',
    'summary': 'Inventory Intelligence tool pack',
    'author': 'AlShayeb Partners',
    'license': 'OPL-1',
    # mrp: the policy pack already refs mrp.model_mrp_production, and
    # check_order_components browses a manufacturing order. The dependency was
    # real and undeclared.
    'depends': ['ai_operations', 'stock', 'mrp',
        'ai_operations_procurement',],
    'data': ['data/policy_pack.xml'],
    'installable': True,
    'application': False,
}
