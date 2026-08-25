"""Service: transactional email delivery through the ODOO integration.

Fallback delivery channel for emails that fail to reach users through the
default SMTP provider (Flask-Mail/SES). ODOO delivers them through its own
outgoing mail server.
"""

import xmlrpc.client

from config import Config
from exception.validation_error import ValidationError
from services import odoo_client
from utils import status


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
        raise delivery_error

    try:
        mail_id = execute(
            "mail.mail",
            "create",
            [{"subject": subject, "body_html": html, "email_to": ",".join(to)}],
            {},
        )

        if not mail_id:
            raise delivery_error

        execute("mail.mail", "send", [[mail_id]], {"raise_exception": True})
    except xmlrpc.client.Fault as exception:
        raise delivery_error from exception

    return mail_id
