from sqlalchemy import func, or_
from sqlalchemy.orm import undefer

from models.main import db, Substance, SubstanceClass
from services import permission_service
from exception.validation_error import ValidationError
from utils import status
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.ADMIN_SUBSTANCES)
def get_substances(
    name=None,
    idClassList=[],
    has_class=None,
    has_admin_text=None,
    class_name=None,
    handling_option="filled",
    handling_type_list=[],
    limit=50,
    offset=0,
):

    q = db.session.query(
        Substance, SubstanceClass, func.count().over().label("count")
    ).outerjoin(SubstanceClass, SubstanceClass.id == Substance.idclass)

    if name != None:
        q = q.filter(Substance.name.ilike(name))

    if class_name != None:
        q = q.filter(SubstanceClass.id.ilike(class_name))

    if len(idClassList) > 0:
        q = q.filter(Substance.idclass.in_(idClassList))

    if len(handling_type_list) > 0:
        handlings = []
        for h in handling_type_list:
            if handling_option == "filled":
                handlings.append(Substance.handling[h].astext != None)
            else:
                handlings.append(Substance.handling[h].astext == None)

        q = q.filter(or_(*handlings))

    if has_class != None:
        if has_class:
            q = q.filter(Substance.idclass != None)
        else:
            q = q.filter(Substance.idclass == None)

    if has_admin_text != None:
        if has_admin_text:
            q = q.filter(Substance.admin_text != None)
        else:
            q = q.filter(Substance.admin_text == None)

    q = (
        q.options(undefer(Substance.handling), undefer(Substance.admin_text))
        .order_by(Substance.name)
        .limit(limit)
        .offset(offset)
    )

    results = q.all()

    if len(results) > 0:
        return {
            "count": results[0].count,
            "data": [
                dict(
                    _to_dto(i[0]), **{"className": i[1].name if i[1] != None else None}
                )
                for i in results
            ],
        }

    return {"count": 0, "data": []}


@has_permission(Permission.ADMIN_SUBSTANCES)
def upsert_substance(data: dict):
    subs = (
        db.session.query(Substance).filter(Substance.id == data.get("id", None)).first()
    )

    if subs is None:
        subs = Substance()
        subs.id = data.get("id")
        db.session.add(subs)

    subs.name = data.get("name", None)
    subs.idclass = data.get("idClass", None)
    subs.active = data.get("active", None)
    subs.link = data.get("link", None)
    subs.handling = data.get("handling", None)
    subs.admin_text = data.get("adminText", None)

    if not subs.handling:
        subs.handling = None

    db.session.flush()

    db_substance = (
        db.session.query(Substance, SubstanceClass)
        .outerjoin(SubstanceClass, SubstanceClass.id == Substance.idclass)
        .filter(Substance.id == subs.id)
        .first()
    )

    return dict(
        _to_dto(db_substance[0]),
        **{"className": db_substance[1].name if db_substance[1] != None else None}
    )


def _to_dto(s: Substance):
    return {
        "id": str(s.id),
        "name": s.name,
        "idClass": s.idclass,
        "active": s.active,
        "link": s.link,
        "handling": s.handling,
        "adminText": s.admin_text,
    }
