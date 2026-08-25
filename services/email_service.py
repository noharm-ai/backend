"""Service: transactional email delivery through the Resend API.

Fallback delivery channel for emails that fail to reach users through the
default SMTP provider (Flask-Mail/SES).
"""

import requests

from config import Config
from exception.validation_error import ValidationError
from utils import status


def send_email(to: list[str], subject: str, html: str) -> dict:
    """Send a transactional email through Resend and return its response payload."""
    if not Config.RESEND_API_KEY:
        raise ValidationError(
            "O serviço de envio de emails não está configurado.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    try:
        response = requests.post(
            Config.RESEND_API_URL,
            headers={"Authorization": f"Bearer {Config.RESEND_API_KEY}"},
            json={
                "from": Config.RESEND_SENDER,
                "to": to,
                "subject": subject,
                "html": html,
            },
            timeout=10,
        )
    except requests.RequestException as exception:
        raise ValidationError(
            "Não foi possível enviar o email. Tente novamente mais tarde.",
            "errors.businessRules",
            status.HTTP_502_BAD_GATEWAY,
        ) from exception

    if response.status_code >= 400:
        raise ValidationError(
            "Não foi possível enviar o email. Tente novamente mais tarde.",
            "errors.businessRules",
            status.HTTP_502_BAD_GATEWAY,
        )

    return response.json()
