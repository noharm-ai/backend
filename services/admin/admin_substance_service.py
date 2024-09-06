from sqlalchemy.orm import undefer
from typing import List

from models.main import db, Substance, User
from services import permission_service
from exception.validation_error import ValidationError
from utils import status


def get_substances(user: User):
    if not permission_service.has_maintainer_permission(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    q = db.session.query(Substance).order_by(Substance.name)
    q = q.options(undefer(Substance.handling))

    return list_to_dto(q.all())


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

    return list_to_dto([db_substance])


def list_to_dto(substances: List[Substance]):
    list = []

    for s in substances:
        list.append(
            {
                "id": s.id,
                "name": s.name,
                "idClass": s.idclass,
                "active": s.active,
                "handling": s.handling,
            }
        )

    return list
