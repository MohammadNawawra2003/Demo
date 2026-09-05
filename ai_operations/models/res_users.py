from odoo import api, fields, models
from odoo.exceptions import AccessDenied, ValidationError


class ResUsers(models.Model):
    """Service-user lifecycle. Document C 10.

    An agent runs as a service user rather than under ``sudo()`` because
    ``sudo()`` grants everything and is invisible in the audit trail, whereas a
    service user grants a defined set, is subject to record rules and ACLs like
    any employee, appears by name in the log, and can be inspected by an auditor
    who does not read Python.
    """

    _inherit = 'res.users'

    is_ai_service_user = fields.Boolean(
        string='AI Service User', default=False, copy=False,
        help="An autonomous agent's execution identity. Such a user must carry "
             "no usable credential and can never authenticate.")

    @api.constrains('is_ai_service_user', 'api_key_ids')
    def _check_ai_service_user_has_no_credential(self):
        """T-69.

        Odoo has no "cannot log in" flag short of archiving, and archiving would
        also stop the agent -- so the mechanism is the *absence of every
        credential*, with :meth:`_check_credentials` as the belt to those braces.
        """
        for user in self:
            if not user.is_ai_service_user:
                continue
            if user.api_key_ids:
                raise ValidationError(
                    "%s is an AI service user and must hold no API key."
                    % user.login)
            if user.share:
                raise ValidationError(
                    "%s is an AI service user and must be an internal user."
                    % user.login)
            # The hash lives in a column the ORM blanks on read, so ask the
            # database. No sudo(), no elevated rights: this is the row we are
            # already validating.
            self.env.cr.execute(
                "SELECT password FROM res_users WHERE id = %s AND password IS NOT NULL "
                "AND password != ''", (user.id,))
            if self.env.cr.fetchone():
                raise ValidationError(
                    "%s is an AI service user and must carry no password. An "
                    "agent identity that can log in is an identity somebody can "
                    "borrow." % user.login)

    def _check_credentials(self, credential, env):
        """The belt. No AI service user authenticates, by any method.

        Read straight from the column so this holds regardless of which ACLs or
        record rules are in force at authentication time.
        """
        if self.id:
            self.env.cr.execute(
                "SELECT is_ai_service_user FROM res_users WHERE id = %s", (self.id,))
            row = self.env.cr.fetchone()
            if row and row[0]:
                raise AccessDenied()
        return super()._check_credentials(credential, env)
