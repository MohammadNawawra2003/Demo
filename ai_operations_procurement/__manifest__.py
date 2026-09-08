{
    'name': 'AI Operations: Procurement',
    'version': '19.0.1.8.0',
    'category': 'Productivity/AI',
    'summary': 'Procurement Intelligence tool pack',
    'author': 'AlShayeb Partners',
    'license': 'OPL-1',
    # mrp: the policy pack has always ref'd mrp.model_mrp_production, and
    # get_shortage_context now browses a manufacturing order to answer
    # "is THIS order short". The dependency was real and undeclared, which
    # is a ParseError waiting for the first install where mrp is absent.
    'depends': ['ai_operations', 'purchase', 'stock', 'mrp'],
    'data': ['data/policy_pack.xml'],
    'installable': True,
    'application': False,
}
