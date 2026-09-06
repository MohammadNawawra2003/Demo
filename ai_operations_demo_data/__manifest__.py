{
    'name': 'AI Operations: Demo Data (NON-PRODUCTION)',
    'version': '19.0.1.0.0',
    'category': 'Productivity/AI',
    'summary': 'NON-PRODUCTION staging and manual-testing configuration for AI Operations',
    'description': """
AI Operations Demo Data -- NON-PRODUCTION
=========================================

Staging and manual-testing configuration ONLY. Never install on production.

It creates no business data: every company, product, vendor, warehouse, BoM,
manufacturing order and quality record it uses is Naqaa's, from
``alshayeb_demo_water``. What it adds is the AI Operations *configuration* a
deployment would otherwise have to enter by hand -- activated agent profiles,
tool assignments, chat channels and demo identities -- so that final manual
testing is four scenarios rather than an afternoon of data entry.

Nothing in production depends on this module, and removing it leaves the
platform working exactly as before. See README.md.
""",
    'author': 'AlShayeb Partners',
    'license': 'OPL-1',
    # Depends on the packs it configures and on the Naqaa business data it
    # reuses. Nothing depends on IT -- that direction is what keeps production
    # installable without it.
    'depends': [
        'ai_operations',
        'ai_operations_anthropic',
        'ai_operations_procurement',
        'ai_operations_manufacturing',
        'alshayeb_demo_water',
    ],
    'data': [
        'data/demo_setup.xml',
    ],
    'installable': True,
    'application': False,
    # Not auto-installable, and never a dependency of anything shipped.
    'auto_install': False,
}
