{
    'name': 'AI Operations: Anthropic Provider',
    'version': '19.0.1.2.0',
    'category': 'Productivity/AI',
    'summary': 'Claude provider adapter for the AI Operations kernel',
    'author': 'AlShayeb Partners',
    'license': 'OPL-1',
    # A provider adapter, not *the* provider. The kernel names no vendor; this
    # module is where the vendor lives, and installing it is a deployment act
    # because it adds an egress destination.
    'depends': ['ai_operations'],
    'data': [],
    'installable': True,
    'application': False,
}
