{
    'name': 'AI Operations: Chat Widget',
    'version': '19.0.1.2.0',
    'category': 'Productivity/AI',
    'summary': 'A floating AI Operations chat launcher in the Odoo backend',
    'description': """
AI Operations Chat Widget
=========================

A small launcher fixed to the bottom-right of the backend that opens a compact
chat panel, so an agent can be reached from anywhere without opening Discuss.

**It is a surface, not a second runtime.** Every message it sends goes through
the same ``discuss.channel`` the Discuss conversation uses, which means the same
guard, the same audit, the same budgets, the same bounded history and the same
company isolation. There is no controller, no new endpoint and no second
execution path: the widget calls ordinary ORM methods, so record rules and ACLs
apply to it exactly as they do everywhere else.

Removing this module removes the launcher and changes nothing else.
""",
    'author': 'AlShayeb Partners',
    'license': 'OPL-1',
    'depends': ['ai_operations', 'web'],
    'data': [],
    'assets': {
        'web.assets_backend': [
            'ai_operations_chat_widget/static/src/chat_widget.scss',
            'ai_operations_chat_widget/static/src/chat_widget.js',
            'ai_operations_chat_widget/static/src/chat_widget.xml',
        ],
        'web.assets_unit_tests': [
            'ai_operations_chat_widget/static/tests/**/*',
        ],
    },
    'installable': True,
    'application': False,
}
