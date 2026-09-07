"""Take the Technical Administrator group back off `admin`. Document C §11.

The kernel shipped `base.user_admin` into **both** administrator groups, which
made §11's separation of duty nil on every installed database: one identity
could enable a capability *and* widen the data scope it runs under, which is the
single thing those two roles exist to keep apart.

Removing the grant from the XML fixes new databases and does nothing to existing
ones — Odoo does not revoke a group membership because a data file stopped
mentioning it. This does.

Security Administrator is left alone: somebody has to be able to open the app.
Enabling a tool becomes a deliberate second act by a second identity, and an
administrator who genuinely needs both can be granted the second group
explicitly, visibly, and revocably.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        DELETE FROM res_groups_users_rel
        WHERE gid = (
            SELECT res_id FROM ir_model_data
            WHERE module = 'ai_operations'
              AND name = 'group_ai_technical_admin'
              AND model = 'res.groups')
          AND uid = (
            SELECT res_id FROM ir_model_data
            WHERE module = 'base' AND name = 'user_admin'
              AND model = 'res.users')
    """)
    if cr.rowcount:
        _logger.warning(
            "ai_operations: removed the Technical Administrator group from "
            "admin. Document C 11 separates enabling a tool from widening an "
            "agent's scope; granting both to one user removed that separation. "
            "Grant it explicitly to a second identity if it is genuinely needed.")
