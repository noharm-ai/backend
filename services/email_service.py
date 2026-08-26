"""Service: transactional email delivery through the ODOO integration.

Fallback delivery channel for emails that fail to reach users through the
default SMTP provider (Flask-Mail/SES). ODOO delivers them through its own
outgoing mail server.
"""

import xmlrpc.client

from config import Config
from exception.validation_error import ValidationError
from services import odoo_client
from utils import logger, status

# Odoo serialises RPC replies with OdooMarshaller(allow_none=False), and
# mail.mail.send() returns None. A *successful* send therefore comes back as a
# fault raised while encoding the response, after the send already ran and
# committed on the Odoo side. Anything that actually goes wrong inside send()
# reports that error instead, so this string is specific to the benign case.
_NONE_REPLY_FAULT = "cannot marshal None"


def _log_fault(step: str, to: list[str], exception: xmlrpc.client.Fault):
    """The caller turns a delivery error into a 200 with delivered=False, so it
    never reaches the endpoint decorator's error logger and nothing is written
    to the audit row. Without this line the branch leaves no trace at all."""
    logger.backend_logger.warning(
        "ODOO email: mail.mail %s raised a fault (recipients: %s) "
        "faultCode=%s faultString=%s",
        step,
        ",".join(to),
        exception.faultCode,
        exception.faultString,
    )


def send_email(to: list[str], subject: str, html: str) -> int:
    """Send a transactional email through ODOO and return the mail record id."""
    if not Config.ODOO_API_URL:
        raise ValidationError(
            "O serviço de envio de emails não está configurado.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    delivery_error = ValidationError(
        "Não foi possível enviar o email. Tente novamente mais tarde.",
        "errors.businessRules",
        status.HTTP_502_BAD_GATEWAY,
    )

    execute = odoo_client.get_client(context="email service")
    if execute is None:
        logger.backend_logger.warning(
            "ODOO email: could not authenticate on the ODOO API (recipients: %s)",
            ",".join(to),
        )
        raise delivery_error

    try:
        mail_id = execute(
            "mail.mail",
            "create",
            [{"subject": subject, "body_html": html, "email_to": ",".join(to)}],
            {},
        )
    except xmlrpc.client.Fault as exception:
        _log_fault("create", to, exception)
        raise delivery_error from exception

    if not mail_id:
        # execute() returns None on socket timeout, so the mail record may still
        # exist in ODOO and be picked up by its outgoing-mail cron
        logger.backend_logger.warning(
            "ODOO email: mail.mail create returned %s (recipients: %s)",
            mail_id,
            ",".join(to),
        )
        raise delivery_error

    try:
        sent = execute("mail.mail", "send", [[mail_id]], {"raise_exception": True})
    except xmlrpc.client.Fault as exception:
        if _NONE_REPLY_FAULT not in (exception.faultString or ""):
            _log_fault("send", to, exception)
            raise delivery_error from exception

        # the mail went out; only the empty reply failed to encode
        sent = True

    if sent is None:
        # timed out waiting on the inline SMTP send: the record is queued in
        # ODOO, so this still reports success. Logged because it is a guess.
        logger.backend_logger.warning(
            "ODOO email: mail.mail send timed out, mail %s left queued (recipients: %s)",
            mail_id,
            ",".join(to),
        )

    return mail_id
