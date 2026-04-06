from sqlalchemy import asc, desc, func, or_

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import Substance, SubstanceClass, db
from utils import status


@has_permission(Permission.READ_BASIC_FEATURES)
def find_substance(term):
    if term == "" or term == None:
        raise ValidationError(
            "Busca inválida",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    items = (
        Substance.query.filter(Substance.name.ilike("%" + term + "%"))
        .order_by(asc(Substance.name))
        .all()
    )

    results = []
    for d in items:
        results.append(
            {
                "sctid": str(d.id),
                "name": d.name.upper(),
            }
        )

    return results


@has_permission(Permission.READ_BASIC_FEATURES)
def find_substance_class(term):
    if term == "" or term == None:
        raise ValidationError(
            "Busca inválida",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    parent = db.aliased(SubstanceClass)

    items = (
        db.session.query(
            SubstanceClass,
            parent.name.label("parent_name"),
            func.concat(
                func.coalesce(parent.name, ""), " - ", SubstanceClass.name
            ).label("concat_field"),
        )
        .filter(
            or_(
                SubstanceClass.name.ilike(f"%{term}%"),
                parent.name.ilike(f"%{term}%"),
                SubstanceClass.id.ilike(f"%{term}%"),
            )
        )
        .outerjoin(parent, SubstanceClass.idParent == parent.id)
        .order_by(asc("concat_field"))
    )

    results = []
    for i in items:
        results.append({"id": i[0].id, "name": i[0].name, "parent": i[1]})

    return results


@has_permission(Permission.READ_BASIC_FEATURES)
def get_substances():
    results = (
        db.session.query(Substance)
        .order_by(desc(Substance.active), asc(Substance.name))
        .all()
    )

    list = []
    for d in results:
        list.append(
            {
                "sctid": str(d.id),
                "name": d.name.upper(),
                "idclass": d.idclass,
                "active": d.active,
            }
        )

    return list


@has_permission(Permission.READ_PRESCRIPTION)
def get_substance_handling(sctid: int, alert_type: str):
    subst = (
        db.session.query(
            Substance.id, Substance.handling[alert_type].label("handling_text")
        )
        .filter(Substance.id == sctid)
        .first()
    )

    if subst and subst.handling_text != None:
        return subst.handling_text

    return None


@has_permission(Permission.READ_BASIC_FEATURES)
def get_substance_classes():
    classes = db.session.query(SubstanceClass).order_by(asc(SubstanceClass.name)).all()

    results = []
    for d in classes:
        results.append(
            {
                "id": d.id,
                "name": d.name.upper(),
            }
        )

    return results
