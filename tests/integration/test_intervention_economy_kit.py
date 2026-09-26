"""Integration tests for the solution-kit price of an intervention's economy.

When a pharmacist intervenes on an item that belongs to a solution, the economy
screen shows not only that item's own price but also the price of the *rest* of
the solution — the "kit". That is what
``intervention_outcome_service._get_price_kit`` builds: given one prescribed
item, it returns the other components of the same group in the same
prescription, each with its catalog price, plus their total.

Which column defines "the same group" depends on the segment the item belongs
to: a CPOE segment groups by ``presmed.cpoe_grupo``, every other segment by
``presmed.slagrupamento``. The function was not covered at all, and the rules
that decide what lands in a kit are easy to break, so they are pinned here
against the real database:

* an item with no group has no kit, and the short circuit returns the total as
  a number while every other path returns it as a string;
* the item being priced is never part of its own kit, and neither is an item of
  another group or of another prescription;
* a component whose drug has no ``medatributos`` row for the segment — or a row
  without a price — is still listed, priced as zero;
* the group column is chosen by the segment, and an item with no segment at all
  falls back to segment 1.

Drugs live in the reserved ``>= 90000`` range (91500 block) and prescriptions
come from the shared test counters, so the session cleanup in
``tests/conftest.py`` removes everything this module writes.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import bindparam, text

from mobile import app as flask_app
from models.main import db
from models.prescription import PrescriptionDrug
from services import intervention_outcome_service
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)

# Segments seeded in the demo schema: 1 is a regular segment, 2 is CPOE.
_SEGMENT = 1
_CPOE_SEGMENT = 2
# Department 3 is the one mapped to the CPOE segment (demo.segmentosetor).
_CPOE_DEPARTMENT = 3

# Drugs reserved for this module (91500 block).
_DRUG_PRICED = 91501  # priced in both segments
_DRUG_PRICED_OTHER_UNIT = 91502  # priced in both segments, different cost unit
_DRUG_NO_PRICE = 91503  # has attributes, but no price
_DRUG_NO_ATTRIBUTES = 91504  # no medatributos row at all
_DRUG_TARGET = 91505  # the item being priced, never part of its own kit

_DRUGS = (
    _DRUG_PRICED,
    _DRUG_PRICED_OTHER_UNIT,
    _DRUG_NO_PRICE,
    _DRUG_NO_ATTRIBUTES,
    _DRUG_TARGET,
)

_PRICE = 2.5
_PRICE_OTHER_UNIT = 4.25
_TARGET_PRICE = 100.0  # large enough that leaking it into the kit is obvious

_PRICE_UNIT = "1"
_OTHER_PRICE_UNIT = "2"

# Attributes are seeded for both segments, so the same drug can be used on a
# CPOE and on a non-CPOE prescription.
_ATTRIBUTES = (
    (_DRUG_PRICED, _PRICE, _PRICE_UNIT),
    (_DRUG_PRICED_OTHER_UNIT, _PRICE_OTHER_UNIT, _OTHER_PRICE_UNIT),
    (_DRUG_NO_PRICE, None, _PRICE_UNIT),
    (_DRUG_TARGET, _TARGET_PRICE, _PRICE_UNIT),
)

_GROUP = 7
_OTHER_GROUP = 8


@pytest.fixture(scope="module", autouse=True)
def seed_drugs(clean_test_artifacts):  # noqa: ARG001
    """Create this module's drugs and their per-segment attributes."""
    _delete_drugs()

    for id_drug in _DRUGS:
        session.execute(
            text(
                "INSERT INTO demo.medicamento (fkmedicamento, fkhospital, nome) "
                "VALUES (:id, 1, :name)"
            ),
            {"id": id_drug, "name": f"ZZTEST KIT {id_drug}"},
        )

    for id_drug, price, price_unit in _ATTRIBUTES:
        for id_segment in (_SEGMENT, _CPOE_SEGMENT):
            session.execute(
                text(
                    "INSERT INTO demo.medatributos "
                    "(fkmedicamento, idsegmento, custo, fkunidademedidacusto) "
                    "VALUES (:id, :segment, :price, :unit)"
                ),
                {
                    "id": id_drug,
                    "segment": id_segment,
                    "price": price,
                    "unit": price_unit,
                },
            )

    session_commit()

    yield

    _delete_drugs()


def _delete_drugs():
    """Remove this module's drugs; the shared cleanup only runs per session."""
    for table in ("medatributos", "medicamento"):
        session.execute(
            text(f"DELETE FROM demo.{table} WHERE fkmedicamento IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": list(_DRUGS)},
        )
    session_commit()


def _next_ids():
    """Reserve a prescription id and an admission number for one test."""
    id_prescription = test_counters["id_prescription"]
    admission_number = test_counters["admission_number"]
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1
    return id_prescription, admission_number


def _create_prescription(cpoe=False):
    """Create an empty prescription on the regular or on the CPOE segment."""
    id_prescription, admission_number = _next_ids()

    create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=1,
        idSegment=_CPOE_SEGMENT if cpoe else _SEGMENT,
        idDepartment=_CPOE_DEPARTMENT if cpoe else 1,
        date=datetime.now(),
        expire=datetime.now() + timedelta(days=1),
    )

    return id_prescription


def _add_item(id_prescription, id_drug, order, group=None, cpoe_group=None, cpoe=False):
    """Add one item to a prescription and return its presmed id.

    ``presmed.cpoe_grupo`` is recomputed by the BEFORE INSERT trigger, so a CPOE
    group is written afterwards with an update.
    """
    id_prescription_drug = int(f"{id_prescription}{order:03}")

    create_prescription_drug(
        id=id_prescription_drug,
        idPrescription=id_prescription,
        idDrug=id_drug,
        idSegment=_CPOE_SEGMENT if cpoe else _SEGMENT,
        solutionGroup=group,
    )

    if cpoe_group is not None:
        session.execute(
            text("UPDATE demo.presmed SET cpoe_grupo = :group WHERE fkpresmed = :id"),
            {"group": cpoe_group, "id": id_prescription_drug},
        )
        session_commit()

    return id_prescription_drug


def _clear_segment(id_prescription_drug):
    """Leave an item without a segment, the way an unprocessed item arrives."""
    session.execute(
        text("UPDATE demo.presmed SET idsegmento = NULL WHERE fkpresmed = :id"),
        {"id": id_prescription_drug},
    )
    session_commit()


@contextmanager
def _demo_schema():
    """Give the service session the demo schema, then throw the session away."""
    with flask_app.app_context():
        db.session.connection(
            execution_options={"schema_translate_map": {None: "demo"}}
        )
        try:
            yield
        finally:
            db.session.rollback()
            db.session.remove()


def _price_kit(id_prescription, id_prescription_drug):
    """Price the kit of one item, the way the outcome calculation does."""
    with _demo_schema():
        prescription_drug = (
            db.session.query(PrescriptionDrug)
            .filter(PrescriptionDrug.id == id_prescription_drug)
            .first()
        )

        return intervention_outcome_service._get_price_kit(
            id_prescription=id_prescription,
            prescription_drug=prescription_drug,
            user=None,
        )


def test_item_without_a_group_has_no_kit():
    """An item that belongs to no solution short circuits to an empty kit."""
    id_prescription = _create_prescription()
    id_item = _add_item(id_prescription, _DRUG_TARGET, 500)
    _add_item(id_prescription, _DRUG_PRICED, 501)

    result = _price_kit(id_prescription, id_item)

    assert result == {"price": 0, "list": []}


def test_the_empty_kit_of_a_grouped_item_still_reports_a_string_price():
    """The short circuit returns the total as a number, every other path as a string.

    Both shapes reach the API, so the difference is pinned rather than hidden.
    """
    id_prescription = _create_prescription()
    id_item = _add_item(id_prescription, _DRUG_TARGET, 500, group=_GROUP)
    _add_item(id_prescription, _DRUG_PRICED, 501, group=_OTHER_GROUP)

    result = _price_kit(id_prescription, id_item)

    assert result == {"price": "0", "list": []}


def test_kit_sums_the_other_components_of_the_solution():
    """Every other item of the group is listed, with its own price and cost unit."""
    id_prescription = _create_prescription()
    id_item = _add_item(id_prescription, _DRUG_TARGET, 500, group=_GROUP)
    _add_item(id_prescription, _DRUG_PRICED, 501, group=_GROUP)
    _add_item(id_prescription, _DRUG_PRICED_OTHER_UNIT, 502, group=_GROUP)

    result = _price_kit(id_prescription, id_item)

    assert result["price"] == str(_PRICE + _PRICE_OTHER_UNIT)
    assert result["list"] == [
        {
            "name": f"ZZTEST KIT {_DRUG_PRICED}",
            "price": str(_PRICE),
            "idMeasureUnit": _PRICE_UNIT,
        },
        {
            "name": f"ZZTEST KIT {_DRUG_PRICED_OTHER_UNIT}",
            "price": str(_PRICE_OTHER_UNIT),
            "idMeasureUnit": _OTHER_PRICE_UNIT,
        },
    ]


def test_the_item_being_priced_is_not_part_of_its_own_kit():
    """The intervened item is excluded, however expensive it is."""
    id_prescription = _create_prescription()
    id_item = _add_item(id_prescription, _DRUG_TARGET, 500, group=_GROUP)
    _add_item(id_prescription, _DRUG_PRICED, 501, group=_GROUP)

    result = _price_kit(id_prescription, id_item)

    assert result["price"] == str(_PRICE)
    assert [component["name"] for component in result["list"]] == [
        f"ZZTEST KIT {_DRUG_PRICED}"
    ]


def test_components_of_another_group_are_ignored():
    """A second solution on the same prescription does not leak into the kit."""
    id_prescription = _create_prescription()
    id_item = _add_item(id_prescription, _DRUG_TARGET, 500, group=_GROUP)
    _add_item(id_prescription, _DRUG_PRICED, 501, group=_GROUP)
    _add_item(id_prescription, _DRUG_PRICED_OTHER_UNIT, 502, group=_OTHER_GROUP)

    result = _price_kit(id_prescription, id_item)

    assert result["price"] == str(_PRICE)
    assert len(result["list"]) == 1


def test_components_of_another_prescription_are_ignored():
    """The same group number on another prescription is a different solution."""
    id_prescription = _create_prescription()
    id_item = _add_item(id_prescription, _DRUG_TARGET, 500, group=_GROUP)
    _add_item(id_prescription, _DRUG_PRICED, 501, group=_GROUP)

    other_prescription = _create_prescription()
    _add_item(other_prescription, _DRUG_PRICED_OTHER_UNIT, 500, group=_GROUP)

    result = _price_kit(id_prescription, id_item)

    assert result["price"] == str(_PRICE)
    assert len(result["list"]) == 1


def test_component_without_attributes_is_listed_as_free():
    """A drug with no medatributos row for the segment is priced as zero."""
    id_prescription = _create_prescription()
    id_item = _add_item(id_prescription, _DRUG_TARGET, 500, group=_GROUP)
    _add_item(id_prescription, _DRUG_NO_ATTRIBUTES, 501, group=_GROUP)

    result = _price_kit(id_prescription, id_item)

    assert result["price"] == "0"
    assert result["list"] == [
        {
            "name": f"ZZTEST KIT {_DRUG_NO_ATTRIBUTES}",
            "price": "0",
            "idMeasureUnit": None,
        }
    ]


def test_component_with_attributes_but_no_price_is_listed_as_free():
    """A curated drug that was never priced keeps its cost unit but costs zero."""
    id_prescription = _create_prescription()
    id_item = _add_item(id_prescription, _DRUG_TARGET, 500, group=_GROUP)
    _add_item(id_prescription, _DRUG_NO_PRICE, 501, group=_GROUP)

    result = _price_kit(id_prescription, id_item)

    assert result["price"] == "0"
    assert result["list"] == [
        {
            "name": f"ZZTEST KIT {_DRUG_NO_PRICE}",
            "price": "0",
            "idMeasureUnit": _PRICE_UNIT,
        }
    ]


def test_unpriced_components_do_not_hide_the_priced_ones():
    """A free component is listed next to the priced ones without changing the total."""
    id_prescription = _create_prescription()
    id_item = _add_item(id_prescription, _DRUG_TARGET, 500, group=_GROUP)
    _add_item(id_prescription, _DRUG_NO_ATTRIBUTES, 501, group=_GROUP)
    _add_item(id_prescription, _DRUG_PRICED, 502, group=_GROUP)

    result = _price_kit(id_prescription, id_item)

    assert result["price"] == str(_PRICE)
    assert len(result["list"]) == 2


def test_cpoe_segment_groups_by_the_cpoe_group():
    """On a CPOE segment the kit is built from cpoe_grupo, not from slagrupamento."""
    id_prescription = _create_prescription(cpoe=True)
    id_item = _add_item(
        id_prescription, _DRUG_TARGET, 500, cpoe_group=_GROUP, cpoe=True
    )
    _add_item(id_prescription, _DRUG_PRICED, 501, cpoe_group=_GROUP, cpoe=True)
    _add_item(
        id_prescription, _DRUG_PRICED_OTHER_UNIT, 502, cpoe_group=_OTHER_GROUP, cpoe=True
    )

    result = _price_kit(id_prescription, id_item)

    assert result["price"] == str(_PRICE)
    assert [component["name"] for component in result["list"]] == [
        f"ZZTEST KIT {_DRUG_PRICED}"
    ]


def test_cpoe_item_without_a_cpoe_group_has_no_kit():
    """On a CPOE segment a solution group alone does not make a kit."""
    id_prescription = _create_prescription(cpoe=True)
    id_item = _add_item(id_prescription, _DRUG_TARGET, 500, group=_GROUP, cpoe=True)
    _add_item(id_prescription, _DRUG_PRICED, 501, group=_GROUP, cpoe=True)

    result = _price_kit(id_prescription, id_item)

    assert result == {"price": 0, "list": []}


def test_cpoe_group_is_not_used_outside_a_cpoe_segment():
    """On a regular segment the cpoe group of the item itself is never the group."""
    id_prescription = _create_prescription()
    id_item = _add_item(id_prescription, _DRUG_TARGET, 500, cpoe_group=_GROUP)
    _add_item(id_prescription, _DRUG_PRICED, 501, cpoe_group=_GROUP)

    result = _price_kit(id_prescription, id_item)

    assert result == {"price": 0, "list": []}


def test_a_component_is_matched_by_either_group_column():
    """The lookup matches the group against both columns, whichever one defined it.

    Here the group comes from ``slagrupamento`` (regular segment), and a
    component that only carries the same number in ``cpoe_grupo`` is pulled in
    as well.
    """
    id_prescription = _create_prescription()
    id_item = _add_item(id_prescription, _DRUG_TARGET, 500, group=_GROUP)
    _add_item(id_prescription, _DRUG_PRICED, 501, cpoe_group=_GROUP)

    result = _price_kit(id_prescription, id_item)

    assert result["price"] == str(_PRICE)
    assert [component["name"] for component in result["list"]] == [
        f"ZZTEST KIT {_DRUG_PRICED}"
    ]


def test_item_without_a_segment_falls_back_to_the_default_segment():
    """With no segment the default (1, not CPOE) decides, so the cpoe group is lost."""
    id_prescription = _create_prescription(cpoe=True)
    id_item = _add_item(
        id_prescription, _DRUG_TARGET, 500, cpoe_group=_GROUP, cpoe=True
    )
    _add_item(id_prescription, _DRUG_PRICED, 501, cpoe_group=_GROUP, cpoe=True)
    _clear_segment(id_item)

    result = _price_kit(id_prescription, id_item)

    assert result == {"price": 0, "list": []}
