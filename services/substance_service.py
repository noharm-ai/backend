from sqlalchemy import or_, asc, func

from models.main import db, Substance, SubstanceClass, Relation
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import status, stringutils, prescriptionutils


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
    results = db.session.query(Substance).order_by(asc(Substance.name)).all()

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


@has_permission(Permission.READ_PRESCRIPTION)
def get_substance_relations(sctid: int):
    SubstA = db.aliased(Substance)
    SubstB = db.aliased(Substance)

    relations = (
        db.session.query(Relation, SubstA.name, SubstB.name)
        .outerjoin(SubstA, SubstA.id == Relation.sctida)
        .outerjoin(SubstB, SubstB.id == Relation.sctidb)
        .filter(or_(Relation.sctida == sctid, Relation.sctidb == sctid))
        .all()
    )

    results = []
    for r in relations:
        if r[0].sctida == sctid:
            sctidB = r[0].sctidb
            nameB = r[2]
        else:
            sctidB = r[0].sctida
            nameB = r[1]

        results.append(
            {
                "sctidB": sctidB,
                "nameB": stringutils.strNone(nameB).upper(),
                "type": r[0].kind,
                "text": r[0].text,
                "active": r[0].active,
                "level": r[0].level,
                "editable": False,
            }
        )

    results.sort(key=prescriptionutils.sortRelations)

    return results


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
