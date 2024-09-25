from utils import status
from sqlalchemy import asc, func

from models.main import db
from models.appendix import *
from models.prescription import *
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError


@has_permission(Permission.ADMIN_INTERVENTION_REASON)
def get_reasons(id=None, active_only=False):
    parent = db.aliased(InterventionReason)
    query_editable = (
        db.session.query(func.count(Intervention.id))
        .select_from(Intervention)
        .filter(Intervention.idInterventionReason.any(InterventionReason.id))
    )

    q = (
        db.session.query(
            InterventionReason,
            parent.description.label("parent_name"),
            func.concat(
                func.coalesce(parent.description, ""), InterventionReason.description
            ).label("concat_field"),
            query_editable.exists().label("protected"),
        )
        .outerjoin(parent, InterventionReason.mamy == parent.id)
        .order_by(asc("concat_field"))
    )

    if id != None:
        q = q.filter(InterventionReason.id == id)

    if active_only:
        q = q.filter(InterventionReason.active == True)

    return q.all()


@has_permission(Permission.ADMIN_INTERVENTION_REASON)
def upsert_reason(id, reason: InterventionReason):
    is_protected = False

    if id != None:
        records = get_reasons(id)
        if len(records) == 0:
            raise ValidationError(
                "Registro inexistente",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )

        record = records[0][0]
        is_protected = records[0][3]
    else:
        record = InterventionReason()

    if not is_protected:
        record.description = reason.description
        record.mamy = reason.mamy

    tp_count = (
        int(reason.substitution) + int(reason.suspension) + int(reason.customEconomy)
    )
    if tp_count > 1:
        raise ValidationError(
            "Você pode escolher somente um tipo de economia para este motivo de intervenção",
            "errors.businessRoles",
            status.HTTP_400_BAD_REQUEST,
        )

    record.idHospital = reason.idHospital
    record.active = reason.active
    record.suspension = reason.suspension
    record.substitution = reason.substitution
    record.customEconomy = reason.customEconomy
    record.relation_type = reason.relation_type

    db.session.add(record)
    db.session.flush()

    return get_reasons(record.id)


def list_to_dto(reasons):
    list = []

    for r in reasons:
        list.append(
            {
                "id": r[0].id,
                "name": r[0].description,
                "parentId": r[0].mamy,
                "parentName": r[1],
                "active": r[0].active,
                "suspension": r[0].suspension,
                "substitution": r[0].substitution,
                "relationType": r[0].relation_type,
                "customEconomy": r[0].customEconomy,
                "protected": r[3],
            }
        )

    return list


def data_to_object(data) -> InterventionReason:
    return InterventionReason(
        description=data.get("name", None),
        mamy=data.get("parentId", None),
        active=data.get("active", False),
        suspension=data.get("suspension", False),
        substitution=data.get("substitution", False),
        customEconomy=data.get("customEconomy", False),
        relation_type=data.get("relationType", 0),
        idHospital=data.get("idHospital", 1),
    )
