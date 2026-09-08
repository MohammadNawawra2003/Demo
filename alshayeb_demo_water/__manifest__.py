{
    'name': 'Naqaa Water — Demo Company',
    'version': '19.0.1.6.0',
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
        # product_expiry is what supplies use_expiration_date, alert_time,
        # removal_time AND the FEFO removal strategy. Without it §5.1's
        # "lot tracked with expiry, 12-month shelf life" and §8.2's FEFO are
        # both silently inert -- the builder guarded on the field existing and
        # skipped every one of them without a word.
        'product_expiry',
        # §13 S-07 is a preventive-maintenance signal on the UV lamp, and a
        # signal needs somewhere to live.
        'maintenance',
        'quality_mrp', 'quality_mrp_workorder',
        'sale_management', 'account', 'l10n_sa', 'hr',
        'stock_security_warehouse',
    ],
    'data': [
        'security/demo_security.xml',
        'security/ir.model.access.csv',
        'data_xml/build.xml',
    ],
    'installable': True,
    'application': False,
}
