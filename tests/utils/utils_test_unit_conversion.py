"""Helpers to create unit-conversion test fixtures in the DB."""

from datetime import datetime

from sqlalchemy import text

from models.main import Drug, Outlier
from tests.conftest import session, session_commit

# IDs reserved for unit-conversion tests — must not overlap with seed data.
# Substances:  public.substancia.sctid  >= 90000
# Drugs:       demo.medicamento          >= 90000
# Outliers:    demo.outlier              >= 90000


def create_test_substance(id: int, name: str, default_measureunit: str | None = "mg") -> None:
    """Insert a substance row into public.substancia.

    Borrows idclasse from an existing seed substance to satisfy the FK constraint.
    Uses ON CONFLICT DO NOTHING so re-running is safe.
    """
    session.execute(
        text(
            "INSERT INTO public.substancia "
            "  (sctid, nome, link, idclasse, ativo, unidadepadrao, update_at, update_by) "
            "VALUES ( "
            "  :id, :name, '', "
            "  (SELECT idclasse FROM public.substancia WHERE sctid < 90000 LIMIT 1), "
            "  true, :default_measureunit, now(), 1 "
            ") ON CONFLICT (sctid) DO NOTHING"
        ),
        {"id": id, "name": name, "default_measureunit": default_measureunit},
    )
    session_commit()


def create_test_drug(id: int, name: str, sctid: int) -> Drug:
    """Insert a drug row into demo.medicamento."""
    drug = Drug()
    drug.id = id
    drug.idHospital = 1
    drug.name = name
    drug.sctid = sctid
    drug.created_at = datetime.now()

    session.add(drug)
    session_commit()

    return drug


def create_test_outlier(id: int, id_drug: int, id_segment: int = 1) -> Outlier:
    """Insert an outlier row into demo.outlier."""
    outlier = Outlier()
    outlier.id = id
    outlier.idDrug = id_drug
    outlier.idSegment = id_segment
    outlier.countNum = 10
    outlier.dose = 100.0
    outlier.frequency = 1.0
    outlier.score = 1

    session.add(outlier)
    session_commit()

    return outlier
