from utils import status
from sqlalchemy.orm import undefer

from models.main import User, db
from models.appendix import SchemaConfig

from services import permission_service
from exception.validation_error import ValidationError


def get_template(user: User):
    if not permission_service.is_admin(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    config_query = (
        db.session.query(SchemaConfig)
        .filter(SchemaConfig.schemaName == user.schema)
        .options(
            undefer(SchemaConfig.nifi_template),
            undefer(SchemaConfig.nifi_status),
            undefer(SchemaConfig.nifi_diagnostics),
        )
    )

    config: SchemaConfig = config_query.first()

    if config == None:
        raise ValidationError(
            "Schema solicitado não possui configuração no banco de dados",
            "errors.businessRule",
            status.HTTP_400_BAD_REQUEST,
        )

    if config.nifi_status == None or config.nifi_template == None:
        raise ValidationError(
            "Template/Status não encontrado",
            "errors.businessRule",
            status.HTTP_400_BAD_REQUEST,
        )

    return {
        "template": config.nifi_template,
        "status": config.nifi_status,
        "diagnostics": config.nifi_diagnostics,
    }
