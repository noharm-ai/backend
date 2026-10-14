"""Integration tests for ``admin_drug_service.fix_inconsistency``.

Score generation (``outlier_service.generate``) refreshes the outliers of a
segment and then calls ``fix_inconsistency``: a drug that gained an outlier but
has no attributes on that segment would be scored without its clinical flags,
so its attributes are filled from the substance it is linked to. The function
had no coverage of its own.

What these tests pin down:

* a drug with an outlier but no attributes on the outlier's segment gets
  attributes on every segment, filled from its substance: the tags become
  flags, the adult or pediatric renal / hepatic limits follow the segment type,
  and the write is stamped with and audited for the caller;
* attributes the drug already has on another segment are kept as they are;
* a drug that already has attributes on its outlier's segment, or that is not
  linked to a substance, is left alone and not counted;
* an empty measure unit stored in the attributes is normalized to null;
* the return value is the number of drugs repaired, and a second run finds
  nothing left to repair;
* the caller needs ADMIN_DRUGS or WRITE_SEGMENT_SCORE.

Each test runs inside a request context and the transaction is rolled back at
the end, so nothing is committed. Ids live in the reserved ``>= 90000`` range
(91500 block), which ``clean_test_artifacts`` also removes.
"""

from contextlib import contextmanager

import pytest
from flask_jwt_extended import verify_jwt_in_request
from sqlalchemy import text

from exception.authorization_error import AuthorizationError
from mobile import app
from models.enums import DrugAttributesAuditTypeEnum
from models.main import db
from security.role import Role
from services.admin import admin_drug_service
from tests.conftest import get_access

SCHEMA = "demo"

# the demo login used by get_access
DEMO_USER_ID = 1

# seed segments 1 and 2 are adult; a pediatric one is added per test
ADULT_SEGMENT = 1
OTHER_ADULT_SEGMENT = 2
PEDIATRIC_SEGMENT = 9150  # medatributos.idsegmento is a smallint

_SUBSTANCE = 9150001

_DRUG_TO_REPAIR = 91501  # outlier on segment 1, no attributes at all
_DRUG_WITH_OTHER_SEGMENT = 91502  # outlier on segment 1, attributes on segment 2
_DRUG_CONSISTENT = 91503  # outlier on segment 1, attributes on segment 1
_DRUG_WITHOUT_SUBSTANCE = 91504  # outlier on segment 1, no sctid

_RENAL_ADULT = 30
_RENAL_PEDIATRIC = 10
_LIVER_ADULT = 20
_LIVER_PEDIATRIC = 5
_CUSTOM_RENAL = 99


@contextmanager
def _service_context(client, roles):
    """Run service calls as the demo user with ``roles``, rolling back at the end."""
    token = get_access(client, roles=roles)

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        verify_jwt_in_request()
        db.session.connection(
            execution_options={"schema_translate_map": {None: SCHEMA}}
        )
        try:
            yield
        finally:
            db.session.rollback()
            db.session.remove()


def _execute(sql: str, params: dict = None):
    """Run a statement on the request session (rolled back with the test).

    Textual statements do not autoflush, so the objects the service left
    pending are flushed first to make them visible.
    """
    db.session.flush()
    return db.session.execute(text(sql), params or {})


def _add_drug(id_drug: int, sctid: int = None, outlier_segment: int = ADULT_SEGMENT):
    """Create a drug with one outlier on ``outlier_segment``."""
    _execute(
        "INSERT INTO demo.medicamento (fkmedicamento, fkhospital, nome, sctid) "
        "VALUES (:id, 1, :name, :sctid)",
        {"id": id_drug, "name": f"ZZTEST FIX INCONSISTENCY {id_drug}", "sctid": sctid},
    )
    _execute(
        "INSERT INTO demo.outlier "
        "(fkmedicamento, idsegmento, contagem, doseconv, frequenciadia, escore) "
        "VALUES (:id, :segment, 10, 1, 1, 1)",
        {"id": id_drug, "segment": outlier_segment},
    )


def _add_attributes(id_drug: int, id_segment: int, renal: int = None, unit=None):
    """Create a demo.medatributos row by hand."""
    _execute(
        "INSERT INTO demo.medatributos "
        "(fkmedicamento, idsegmento, renal, fkunidademedida) "
        "VALUES (:id, :segment, :renal, :unit)",
        {"id": id_drug, "segment": id_segment, "renal": renal, "unit": unit},
    )


def _attributes(id_drug: int) -> dict:
    """The drug's attributes, keyed by segment."""
    rows = _execute(
        "SELECT * FROM demo.medatributos WHERE fkmedicamento = :id",
        {"id": id_drug},
    ).mappings()

    return {row["idsegmento"]: row for row in rows}


def _seed():
    """A substance, a pediatric segment and the drugs of this module."""
    _execute(
        "INSERT INTO public.substancia "
        "(sctid, nome, link, ativo, tags, renal_adulto, renal_pediatrico, "
        "hepatico_adulto, hepatico_pediatrico, plaquetas, risco_queda, lactante, "
        "gestante) "
        "VALUES (:sctid, 'ZZTEST FIX INCONSISTENCY SUBSTANCIA', '', true, "
        "ARRAY['antimicro', 'pim'], :renal_adult, :renal_ped, :liver_adult, "
        ":liver_ped, 50000, 2, 's', 'n')",
        {
            "sctid": _SUBSTANCE,
            "renal_adult": _RENAL_ADULT,
            "renal_ped": _RENAL_PEDIATRIC,
            "liver_adult": _LIVER_ADULT,
            "liver_ped": _LIVER_PEDIATRIC,
        },
    )
    _execute(
        "INSERT INTO demo.segmento (idsegmento, nome, status, tp_segmento) "
        "VALUES (:id, 'ZZTEST Segmento Pediatrico', 1, 2)",
        {"id": PEDIATRIC_SEGMENT},
    )

    _add_drug(_DRUG_TO_REPAIR, sctid=_SUBSTANCE)

    _add_drug(_DRUG_WITH_OTHER_SEGMENT, sctid=_SUBSTANCE)
    _add_attributes(_DRUG_WITH_OTHER_SEGMENT, OTHER_ADULT_SEGMENT, renal=_CUSTOM_RENAL)

    _add_drug(_DRUG_CONSISTENT, sctid=_SUBSTANCE)
    _add_attributes(_DRUG_CONSISTENT, ADULT_SEGMENT, renal=_CUSTOM_RENAL)

    _add_drug(_DRUG_WITHOUT_SUBSTANCE)


@pytest.fixture
def curator_context(client):
    """A CURATOR service context with the seed data of this module in place.

    The seed schema may hold inconsistent drugs of its own, so a first run
    repairs those before the module's drugs are created; the counts asserted
    below are then exactly the module's.
    """
    with _service_context(client, [Role.CURATOR.value]):
        admin_drug_service.fix_inconsistency()
        _seed()
        yield


def test_repairs_a_drug_on_every_segment(curator_context):  # noqa: ARG001
    """A drug missing attributes on its outlier's segment gets them on every segment."""
    admin_drug_service.fix_inconsistency()

    attributes = _attributes(_DRUG_TO_REPAIR)

    assert set(attributes) >= {ADULT_SEGMENT, OTHER_ADULT_SEGMENT, PEDIATRIC_SEGMENT}


def test_fills_the_attributes_from_the_substance(curator_context):  # noqa: ARG001
    """The substance's tags and limits become the drug's attributes."""
    admin_drug_service.fix_inconsistency()

    adult = _attributes(_DRUG_TO_REPAIR)[ADULT_SEGMENT]

    # tags present on the substance
    assert adult["antimicro"] is True
    assert adult["idoso"] is True
    # tags absent from the substance
    assert adult["mav"] is False
    assert adult["controlados"] is False
    assert adult["sonda"] is False
    assert adult["quimio"] is False

    assert adult["renal"] == _RENAL_ADULT
    assert adult["hepatico"] == _LIVER_ADULT
    assert adult["plaquetas"] == 50000
    assert adult["risco_queda"] == 2
    assert adult["lactante"] == "s"
    assert adult["gestante"] == "n"


def test_uses_the_pediatric_limits_on_a_pediatric_segment(curator_context):  # noqa: ARG001
    """Renal and hepatic limits follow the segment type."""
    admin_drug_service.fix_inconsistency()

    pediatric = _attributes(_DRUG_TO_REPAIR)[PEDIATRIC_SEGMENT]

    assert pediatric["renal"] == _RENAL_PEDIATRIC
    assert pediatric["hepatico"] == _LIVER_PEDIATRIC


def test_stamps_and_audits_the_repair(curator_context):  # noqa: ARG001
    """Every attribute written is stamped with the caller and audited."""
    admin_drug_service.fix_inconsistency()

    attributes = _attributes(_DRUG_TO_REPAIR)
    assert {row["update_by"] for row in attributes.values()} == {DEMO_USER_ID}
    assert all(row["update_at"] is not None for row in attributes.values())

    audits = _execute(
        "SELECT idsegmento, tp_audit, created_by FROM demo.medatributos_audit "
        "WHERE fkmedicamento = :id",
        {"id": _DRUG_TO_REPAIR},
    ).all()

    assert {row.idsegmento for row in audits} == set(attributes)
    assert {row.tp_audit for row in audits} == {
        DrugAttributesAuditTypeEnum.UPSERT_UPDATE_SUBSTANCE.value
    }
    assert {row.created_by for row in audits} == {DEMO_USER_ID}


def test_keeps_attributes_already_set_on_another_segment(curator_context):  # noqa: ARG001
    """Only the missing segments are filled; existing attributes are not overwritten."""
    admin_drug_service.fix_inconsistency()

    attributes = _attributes(_DRUG_WITH_OTHER_SEGMENT)

    assert attributes[ADULT_SEGMENT]["renal"] == _RENAL_ADULT
    assert attributes[OTHER_ADULT_SEGMENT]["renal"] == _CUSTOM_RENAL
    assert attributes[OTHER_ADULT_SEGMENT]["update_by"] is None


def test_leaves_a_consistent_drug_alone(curator_context):  # noqa: ARG001
    """A drug with attributes on its outlier's segment is not touched."""
    admin_drug_service.fix_inconsistency()

    attributes = _attributes(_DRUG_CONSISTENT)

    assert set(attributes) == {ADULT_SEGMENT}
    assert attributes[ADULT_SEGMENT]["renal"] == _CUSTOM_RENAL


def test_skips_a_drug_without_substance(curator_context):  # noqa: ARG001
    """With no substance to copy from, the drug is left without attributes."""
    admin_drug_service.fix_inconsistency()

    assert _attributes(_DRUG_WITHOUT_SUBSTANCE) == {}


def test_returns_the_number_of_repaired_drugs(curator_context):  # noqa: ARG001
    """Only the two drugs missing attributes on their outlier's segment count."""
    assert admin_drug_service.fix_inconsistency() == 2


def test_a_second_run_finds_nothing_to_repair(curator_context):  # noqa: ARG001
    """Once repaired, the drugs no longer show up as inconsistent."""
    admin_drug_service.fix_inconsistency()

    assert admin_drug_service.fix_inconsistency() == 0


def test_normalizes_an_empty_measure_unit(curator_context):  # noqa: ARG001
    """An empty measure unit in the attributes is stored as null."""
    _add_attributes(_DRUG_CONSISTENT, OTHER_ADULT_SEGMENT, unit="")
    _add_attributes(_DRUG_WITHOUT_SUBSTANCE, ADULT_SEGMENT, unit="mg")

    admin_drug_service.fix_inconsistency()

    assert _attributes(_DRUG_CONSISTENT)[OTHER_ADULT_SEGMENT]["fkunidademedida"] is None
    assert (
        _attributes(_DRUG_WITHOUT_SUBSTANCE)[ADULT_SEGMENT]["fkunidademedida"] == "mg"
    )


def test_requires_admin_drugs_or_write_segment_score(client):
    """A PRESCRIPTION_ANALYST holds neither permission and is refused."""
    with _service_context(client, [Role.PRESCRIPTION_ANALYST.value]):
        with pytest.raises(AuthorizationError):
            admin_drug_service.fix_inconsistency()
