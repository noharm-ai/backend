"""Service: solicitation attribute related operations"""

from datetime import datetime

from decorators.has_permission_decorator import has_permission, Permission
from models.main import User, db
from models.regulation import RegSolicitationAttribute, RegSolicitation
from models.requests.regulation_solicitation_attribute_request import (
    RegulationSolicitationAttributeRequest,
    RegSolicitationAttributeListRequest,
)
from exception.validation_error import ValidationError
from utils import status, dateutils


@has_permission(Permission.WRITE_REGULATION)
def remove(idreg_solicitation_attribute: int, user_context: User):
    """set attribute status to removed"""
    attribute = (
        db.session.query(RegSolicitationAttribute)
        .filter(RegSolicitationAttribute.id == idreg_solicitation_attribute)
        .first()
    )

    if not attribute:
        raise ValidationError(
            "Registro inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    attribute.tp_status = 2
    attribute.updated_at = datetime.now()
    attribute.updated_by = user_context.id
    db.session.flush()

    return {
        "id": attribute.id,
        "tpAttribute": attribute.tp_attribute,
        "status": attribute.tp_status,
        "createdAt": dateutils.to_iso(attribute.created_at),
        "value": attribute.value,
    }


@has_permission(Permission.WRITE_REGULATION)
def create(request_data: RegulationSolicitationAttributeRequest, user_context: User):
    """Creates new attributes"""

    solicitation = (
        db.session.query(RegSolicitation)
        .filter(RegSolicitation.id == request_data.idRegSolicitation)
        .first()
    )

    if not solicitation:
        raise ValidationError(
            "Registro inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    attribute = RegSolicitationAttribute()
    attribute.id_reg_solicitation = solicitation.id
    attribute.tp_attribute = request_data.tpAttribute
    attribute.tp_status = 1
    attribute.value = request_data.value

    attribute.created_at = datetime.today()
    attribute.created_by = user_context.id
    db.session.add(attribute)
    db.session.flush()

    return {
        "id": attribute.id,
        "tpAttribute": attribute.tp_attribute,
        "status": attribute.tp_status,
        "createdAt": dateutils.to_iso(attribute.created_at),
        "value": attribute.value,
    }


@has_permission(Permission.READ_REGULATION)
def get_attributes(request_data: RegSolicitationAttributeListRequest):
    """List solicitation attributes by type"""
    attributes = (
        db.session.query(RegSolicitationAttribute, User.name.label("createdByName"))
        .outerjoin(User, RegSolicitationAttribute.created_by == User.id)
        .filter(
            RegSolicitationAttribute.id_reg_solicitation
            == request_data.idRegSolicitation
        )
        .filter(RegSolicitationAttribute.tp_attribute == request_data.tpAttribute)
        .filter(RegSolicitationAttribute.tp_status == 1)
        .order_by(RegSolicitationAttribute.created_at)
        .all()
    )

    results = []
    for attribute in attributes:
        results.append(
            {
                "id": attribute.RegSolicitationAttribute.id,
                "tpAttribute": attribute.RegSolicitationAttribute.tp_attribute,
                "status": attribute.RegSolicitationAttribute.tp_status,
                "createdAt": dateutils.to_iso(
                    attribute.RegSolicitationAttribute.created_at
                ),
                "createdBy": attribute.createdByName,
                "value": attribute.RegSolicitationAttribute.value,
            }
        )

    return results
