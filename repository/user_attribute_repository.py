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
