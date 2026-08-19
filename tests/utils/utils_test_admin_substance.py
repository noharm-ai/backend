"""Helpers to create admin-substance test fixtures in the DB.

Rows live in the shared ``public.substancia`` / ``public.classe`` tables.
Substance ids in the 95000+ range are reserved for this module: they sit inside
the ``sctid >= 90000`` window wiped by ``tests/conftest.py::_cleanup`` while
staying clear of the 90001-90006 ids used by the unit-conversion tests.
"""

from sqlalchemy import text

from tests.conftest import session, session_commit


def create_test_substance_class(id_class: str, name: str) -> None:
    """Insert a substance class into public.classe (idempotent)."""
    session.execute(
        text(
            "INSERT INTO public.classe (idclasse, idclassemae, nome) "
            "VALUES (:id, :id, :name) ON CONFLICT (idclasse) DO NOTHING"
        ),
        {"id": id_class, "name": name},
    )
    session_commit()


def create_test_substance(
    id: int,
    name: str,
    id_class: str | None = None,
    active: bool = True,
    admin_text: str | None = None,
    default_measureunit: str | None = None,
    maxdose_adult: float | None = None,
    maxdose_adult_weight: float | None = None,
    maxdose_pediatric: float | None = None,
    maxdose_pediatric_weight: float | None = None,
    tags: list[str] | None = None,
    updated_by: int = 1,
) -> None:
    """Insert a substance row into public.substancia (idempotent)."""
    session.execute(
        text(
            "INSERT INTO public.substancia "
            "  (sctid, nome, link, idclasse, ativo, curadoria, unidadepadrao, "
            "   dosemax_adulto, dosemax_peso_adulto, dosemax_pediatrico, "
            "   dosemax_peso_pediatrico, tags, update_at, update_by) "
            "VALUES "
            "  (:id, :name, '', :id_class, :active, :admin_text, :default_measureunit, "
            "   :maxdose_adult, :maxdose_adult_weight, :maxdose_pediatric, "
            "   :maxdose_pediatric_weight, :tags, now(), :updated_by) "
            "ON CONFLICT (sctid) DO NOTHING"
        ),
        {
            "id": id,
            "name": name,
            "id_class": id_class,
            "active": active,
            "admin_text": admin_text,
            "default_measureunit": default_measureunit,
            "maxdose_adult": maxdose_adult,
            "maxdose_adult_weight": maxdose_adult_weight,
            "maxdose_pediatric": maxdose_pediatric,
            "maxdose_pediatric_weight": maxdose_pediatric_weight,
            "tags": tags,
            "updated_by": updated_by,
        },
    )
    session_commit()


def set_substance_handling(id: int, handling: str) -> None:
    """Set the ``manejo`` jsonb column of a substance (raw json string)."""
    session.execute(
        text("UPDATE public.substancia SET manejo = CAST(:handling AS jsonb) WHERE sctid = :id"),
        {"id": id, "handling": handling},
    )
    session_commit()


def get_substance_row(id: int):
    """Read a substance straight from the DB, bypassing the service layer."""
    return session.execute(
        text(
            "SELECT sctid, nome, idclasse, ativo, unidadepadrao, dosemax_adulto, "
            "       manejo, curadoria, tags, update_by, divisor_faixa "
            "FROM public.substancia WHERE sctid = :id"
        ),
        {"id": id},
    ).first()
