"""Helpers to create unit-conversion test fixtures in the DB."""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from models.appendix import MeasureUnit, MeasureUnitConvert
from models.main import Drug, DrugAttributes, Outlier, PrescriptionAgg
from tests.conftest import session, session_commit

# IDs reserved for unit-conversion tests — must not overlap with seed data.
# Substances:  public.substancia.sctid  >= 90000
# Drugs:       demo.medicamento          >= 90000
# Outliers:    demo.outlier              >= 90000


def create_test_measure_unit(id: str, description: str, measureunit_nh: str) -> None:
    """Upsert a row into demo.unidademedida (idempotent — safe if already in seed data)."""
    session.execute(
        insert(MeasureUnit)
        .values(
            id=id,
            idHospital=1,
            description=description,
            measureunit_nh=measureunit_nh,
        )
        .on_conflict_do_nothing()
    )
    session_commit()


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


def create_test_prescription_agg(
    id_drug: int,
    id_measure_unit: str,
    id_department: int = 1,
    id_frequency: str = "1x",
    dose: float = 100.0,
) -> PrescriptionAgg:
    """Insert a prescricaoagg row to register a drug's prescribed unit."""
    agg = PrescriptionAgg()
    agg.idHospital = 1
    agg.idDepartment = id_department
    agg.idSegment = 1
    agg.idDrug = id_drug
    agg.idMeasureUnit = id_measure_unit
    agg.idFrequency = id_frequency
    agg.dose = dose
    agg.doseconv = dose
    agg.frequency = 1.0
    agg.countNum = 5

    session.add(agg)
    session_commit()

    return agg


def create_test_measure_unit_convert(
    id_drug: int,
    id_measure_unit: str,
    id_segment: int = 1,
    factor: float = 1000.0,
) -> MeasureUnitConvert:
    """Insert a unidadeconverte row with the given conversion factor."""
    convert = MeasureUnitConvert()
    convert.idDrug = id_drug
    convert.idMeasureUnit = id_measure_unit
    convert.idSegment = id_segment
    convert.factor = factor

    session.add(convert)
    session_commit()

    return convert


def create_test_drug_attributes(
    id_drug: int,
    id_segment: int = 1,
    id_measure_unit: str = "mg",
) -> DrugAttributes:
    """Insert a medatributos row that sets the drug's default measure unit."""
    attrs = DrugAttributes()
    attrs.idDrug = id_drug
    attrs.idSegment = id_segment
    attrs.idMeasureUnit = id_measure_unit

    session.add(attrs)
    session_commit()

    return attrs
