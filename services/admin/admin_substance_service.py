from sqlalchemy import func
from sqlalchemy.orm import undefer
from typing import List

from models.main import db, Substance, User, SubstanceClass
from services import permission_service
from exception.validation_error import ValidationError
from utils import status


def get_substances(
    user: User,
    name=None,
    limit=50,
    offset=0,
):
    if not permission_service.has_maintainer_permission(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    q = db.session.query(
        Substance, SubstanceClass, func.count().over().label("count")
    ).outerjoin(SubstanceClass, SubstanceClass.id == Substance.idclass)

    if name != None:
        q = q.filter(Substance.name.ilike(name))

    q = (
        q.options(undefer(Substance.handling))
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


def upsert_substance(data: dict, user):
    if not permission_service.has_maintainer_permission(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    subs = (
        db.session.query(Substance).filter(Substance.id == data.get("id", None)).first()
    )

    if subs is None:
        subs = Substance()
        subs.id = data.get("id")
        db.session.add(subs)

    subs.name = data.get("name", None)
    subs.idclass = data.get("idclass", None)
    subs.active = data.get("active", None)
    subs.handling = data.get("handling")

    db.session.flush()

    db_substance = db.session.query(Substance).filter(Substance.id == subs.id).first()

    # todo
    # return list_to_dto([db_substance])


def _to_dto(s: Substance):
    return {
        "id": s.id,
        "name": s.name,
        "idClass": s.idclass,
        "active": s.active,
        "link": s.link,
        "handling": s.handling,
    }
