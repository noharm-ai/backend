"""Service: who reaches the reads the infection control pages make.

Some of those reads (cultures, exam history, antimicrobial search) belong to
other permissions too, mainly READ_PRESCRIPTION. A role that only views the
infection control data (READ_INFECTION_CONTROL, e.g. CONFIG_MANAGER) reaches
them as well, but only in a schema with the infection control feature on.
"""

from exception.validation_error import ValidationError
from models.enums import FeatureEnum
from security.permission import Permission
from services import feature_service
from utils import status


def check_feature():
    """Raises when the schema doesn't have the infection control feature on"""
    if not feature_service.has_feature(FeatureEnum.INFECTION_CONTROL):
        raise ValidationError(
            "Controle de infecção não está habilitado",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )


def check_read_access(user_permissions: list[Permission], own: list[Permission]):
    """A read the infection control pages make, open to READ_INFECTION_CONTROL
    besides its own permissions (`own`): a user reaching it only through
    READ_INFECTION_CONTROL needs the feature on. Call it from a service whose
    @has_permission lists `own` and READ_INFECTION_CONTROL"""
    if any(permission in user_permissions for permission in own):
        return

    check_feature()
