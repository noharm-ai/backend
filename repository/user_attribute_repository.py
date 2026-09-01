"""Repository: User attribute (generic per-user metadata) operations"""

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from models.main import db, UserAttribute


def get_value(id_user: int, kind: str) -> str | None:
    """Return the attribute value for a user, or None when it was never set"""
    attribute = (
        db.session.query(UserAttribute)
        .filter(UserAttribute.idUser == id_user)
        .filter(UserAttribute.kind == kind)
        .first()
    )

    return attribute.value if attribute else None


def set_value(id_user: int, kind: str, value: str, responsible_id: int):
    """Insert or update one attribute for a user"""
    now = datetime.today()

    stmt = insert(UserAttribute.__table__).values(
        idusuario=id_user,
        tipo=kind,
        valor=value,
        created_at=now,
        created_by=responsible_id,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["idusuario", "tipo"],
        set_={"valor": value, "updated_at": now, "updated_by": responsible_id},
    )

    db.session.execute(stmt)


def list_users_with_attribute(user_ids: list, kind: str) -> set:
    """Ids of the given users that hold an attribute row of this kind.

    Presence only, in a single query: callers resolving a whole list must not
    fall back to get_value() per user"""
    if not user_ids:
        return set()

    results = (
        db.session.query(UserAttribute.idUser)
        .filter(UserAttribute.idUser.in_(user_ids))
        .filter(UserAttribute.kind == kind)
        .all()
    )

    return {id_user for (id_user,) in results}
