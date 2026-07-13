"""Repository: User numbers (rough usage counters) operations"""

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from models.main import db, UserNumbers


def _increment(user_id: int, field: str):
    """Increment one counter field for a user, creating the row if needed"""
    now = datetime.today()

    stmt = insert(UserNumbers.__table__).values(
        idusuario=user_id,
        **{field: 1},
        created_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["idusuario"],
        set_={
            field: func.coalesce(UserNumbers.__table__.c[field], 0) + 1,
            "updated_at": now,
        },
    )

    db.session.execute(stmt)


def increment_logins(user_id: int):
    """Increment the login counter for a user"""
    _increment(user_id, "logins")


def increment_checks(user_id: int):
    """Increment the prescription check counter for a user"""
    _increment(user_id, "checagens")


def increment_interventions(user_id: int):
    """Increment the intervention counter for a user"""
    _increment(user_id, "intervencoes")


def increment_evolutions(user_id: int):
    """Increment the evolution (clinical notes) counter for a user"""
    _increment(user_id, "evolucoes")
