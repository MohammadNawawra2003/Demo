{
    'name': 'AI Operations',
    'version': '19.0.1.17.0',
    'category': 'Productivity/AI',
    'summary': 'Secure execution platform for departmental AI agents',
    'author': 'AlShayeb Partners',
    'license': 'OPL-1',
    'depends': ['base', 'mail'],          # NOTHING ELSE. EVER.
    # Document D 3.1 lists the FINAL data set. Session 1 ships only what
    # Session 1 builds -- referencing a view for a model that does not exist
    # yet would break the bare-database install that is this session's STOP
    # gate. tool_views / handoff_views / audit_log_views / ir_sequence.xml
    # arrive with their models in Sessions 2, 3 and 9.
    'data': [
        'security/ai_operations_groups.xml',
        'security/ir.model.access.csv',
        'security/ir_rule.xml',
        'data/ir_sequence.xml',
        'views/agent_profile_views.xml',
        'views/model_permission_views.xml',
        'views/action_permission_views.xml',
        'views/tool_views.xml',
        'views/menus.xml',
        # after menus.xml: it hangs the Audit Log entry off the root menu
        'views/audit_log_views.xml',
        'views/handoff_views.xml',
    ],
    'installable': True,
    'application': True,
}
