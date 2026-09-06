{
    'name': 'AI Operations: Manufacturing',
    'version': '19.0.1.2.0',
    'category': 'Productivity/AI',
    'summary': 'Manufacturing Intelligence tool pack',
    'author': 'AlShayeb Partners',
    'license': 'OPL-1',
    # Depends on the procurement pack only so MATERIAL_SHORTAGE can name its
    # receiver. No code is shared, and no capability crosses.
    'depends': ['ai_operations', 'ai_operations_procurement', 'mrp', 'stock'],
    'data': ['data/policy_pack.xml'],
    'installable': True,
    'application': False,
}
