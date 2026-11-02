"""Service: admin drug related operations"""

from sqlalchemy.orm import undefer

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import Substance, db
from utils import status


@has_permission(Permission.ADMIN_DRUGS)
def get_drug_ref(sctid: int):
    subst = (
        db.session.query(Substance)
        .filter(Substance.id == sctid)
        .options(undefer(Substance.admin_text))
        .first()
    )

    if subst == None:
        raise ValidationError(
            "Substância inválido",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    return {"name": subst.name, "ref": subst.admin_text}
