from utils import status
from markupsafe import escape
from datetime import datetime

from models.main import User, db
from models.appendix import NifiStatus, NifiQueue

from services import permission_service
from exception.validation_error import ValidationError


def get_template(user: User):
    if not permission_service.is_admin(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    config: NifiStatus = db.session.query(NifiStatus).first()

    if config == None:
        raise ValidationError(
            "Registro não encontrado",
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
        "updatedAt": config.updatedAt.isoformat(),
    }


def set_state(id_processor: str, state: str, user: User):
    if not permission_service.is_admin(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    queue = NifiQueue()
    queue.url = f"nifi-api/processors/{escape(id_processor)}/diagnostics"
    queue.method = "GET"
    queue.runStatus = True
    queue.body = {"state": state}
    queue.createdAt = datetime.today()

    db.session.add(queue)
    db.session.flush()

    return queue.id
