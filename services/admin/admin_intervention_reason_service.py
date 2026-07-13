"""Service: admin intervention reason operations"""

from sqlalchemy import asc, func, literal_column

from decorators.has_permission_decorator import Permission, has_permission
from models.appendix import InterventionReason
from models.main import db
from models.prescription import Intervention


@has_permission(Permission.ADMIN_INTERVENTION_REASON, Permission.READ_PRESCRIPTION)
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
            query_editable.exists().label("protected")
            if not active_only
            else literal_column("0"),
        )
        .outerjoin(parent, InterventionReason.mamy == parent.id)
        .order_by(asc("concat_field"))
    )

    if id != None:
        q = q.filter(InterventionReason.id == id)

    if active_only:
        q = q.filter(InterventionReason.active == True)

    return q.all()


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
                "blocking": r[0].blocking,
                "protected": r[3],
                "ram": r[0].ram,
            }
        )

    return list
