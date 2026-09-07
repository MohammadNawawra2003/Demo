{
    'name': 'AI Operations: General Manager',
    'version': '19.0.1.0.0',
    'category': 'Productivity/AI',
    'summary': 'General Manager Intelligence: a read-only cross-department '
               'executive view. No write tool, no handoff, no activity.',
    'author': 'AlShayeb Partners',
    'license': 'OPL-1',
    # quality_mrp is Enterprise, so this pack is Enterprise-tier like the
    # manufacturing and quality packs. Recorded in DEVIATIONS.md: a General
    # Manager who cannot see open quality issues is not the agent George asked
    # for, and quality.alert has no Community equivalent.
    'depends': ['ai_operations', 'sale', 'purchase', 'stock', 'mrp', 'account',
        'quality_mrp',],
    'data': ['data/policy_pack.xml'],
    'installable': True,
    'application': False,
}
