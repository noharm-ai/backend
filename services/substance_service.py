from sqlalchemy import or_

from models.main import db
from models.appendix import *
from models.prescription import *

from exception.validation_error import ValidationError


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
                "sctid": d.id,
                "name": d.name.upper(),
            }
        )

    return results


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
