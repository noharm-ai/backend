"""Service to manage and retrieve integration status information for the admin interface."""

from models.main import db
from models.appendix import SchemaConfig, Frequency
from exception.validation_error import ValidationError
from utils import status


def get_integration_status(schema):
    config = (
        db.session.query(SchemaConfig).filter(SchemaConfig.schemaName == schema).first()
    )

    if config == None:
        raise ValidationError(
            "Schema inválido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    return config.status


def _get_pending_frequencies():
    return db.session.query(Frequency).filter(Frequency.dailyFrequency == None).count()
