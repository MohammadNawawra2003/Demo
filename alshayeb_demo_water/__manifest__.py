{
    'name': 'Naqaa Water — Demo Company',
    'version': '19.0.1.0.0',
    'category': 'Productivity/AI',
    'summary': 'The archetype Saudi bottled-water company the AI platform is '
               'built, demonstrated and security-tested against',
    'author': 'AlShayeb Partners',
    'license': 'OPL-1',
    # Depends on NO ai_operations, in either direction. The demo database must
    # install standalone: it is the regression baseline, not a dependency of the
    # product. Document A §16.
    #
    # l10n_sa_edi (ZATCA Phase 2) is deliberately absent: it is Enterprise-only
    # and accounting exists here purely as an isolation target in Phase 1. See
    # DEVIATIONS.md.
    'depends': [
        'purchase', 'stock', 'mrp',
        'quality_mrp', 'quality_mrp_workorder',
        'sale_management', 'account', 'l10n_sa', 'hr',
        'stock_security_warehouse',
    ],
    'data': [
        'security/demo_security.xml',
        'security/ir.model.access.csv',
    ],
    'post_init_hook': 'build_demo_company',
    'installable': True,
    'application': False,
}
