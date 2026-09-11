"""Integration tests for the drug score-generation config endpoints.

Before a drug can be scored, a curator has to tell the backend how to read its
doses. That is what ``POST /outliers/generate/config/<segment>/<drug>`` does, and
neither it nor its ``/v2`` variant had any coverage — yet between them they own
four decisions that change the numbers the pharmacist later sees:

* the payload guards — a missing measure unit and a division of ``1`` are
  refused, and the caller must be authorized on the segment;
* ``medatributos`` is created from the substance reference when the drug has no
  row for the segment yet, and updated in place when it has;
* every ``measureUnitList`` entry becomes (or updates) one ``unidadeconverte``
  factor for the segment — the v1 endpoint only;
* the maximum dose is recalculated from the substance reference through the
  factor that was just saved, so a wrong factor silently moves ``dosemaxima``.

The ``/v2`` route exists because the current curator screen configures the
measure units on its own screen: it passes ``skip_measure_unit``, which drops
both the unit guard and the conversion write while keeping everything else.

Each test configures its own drug, so the module has no internal ordering.
Fixtures use the reserved ``>= 90000`` id range (91100 block) so the
session-scoped ``clean_test_artifacts`` fixture removes them. The measure unit
this module needs falls outside that window, so it is removed here on teardown.
"""

import pytest
from sqlalchemy import text

from models.appendix import MeasureUnitConvert
from models.enums import DrugAttributesAuditTypeEnum
from models.main import DrugAttributes, DrugAttributesAudit
from tests.conftest import session, session_commit
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_substance,
)
from utils import status

CONFIG_URL = "/outliers/generate/config"

_SEGMENT = 1
# the demo user is authorized on segments 1 and 2 only
_UNAUTHORIZED_SEGMENT = 3

# the demo user behind the config_manager_headers fixture
CALLER_ID = 1

# Ids reserved for this module (91100 block, distinct from other modules').
_SCTID_REF = 91101  # carries the reference max doses
_SCTID_PLAIN = 91102  # no reference dose at all

_DRUG_CREATE = 91101  # has no medatributos row until the test configures it
_DRUG_EXISTING = 91102  # configured twice, asserts the update in place
_DRUG_UNITS = 91103  # receives two conversion factors
_DRUG_REFACTORED = 91104  # configured twice with different factors
_DRUG_DIVISION = 91105  # asserts the 0 -> NULL normalization
_DRUG_MAXDOSE = 91106  # asserts the converted reference dose
_DRUG_MAXDOSE_WEIGHT = 91107  # same, but by weight
_DRUG_NO_REFERENCE = 91108  # substance without reference doses
_DRUG_V2 = 91109  # configured through /v2
_DRUG_V2_UNITS = 91110  # asserts /v2 writes no conversion
_DRUG_REJECTED = 91111  # receives the payloads that must be refused
_UNKNOWN_DRUG = 91199

# A measure unit of our own, mapped onto the NoHarm "mg" the substances default
# to: ``calculate_dosemax_uniq`` converts through ``unidademedida_nh``, and no
# seed unit has it filled in.
_MEASURE_UNIT = "ZZCFGMG"
# a second unit, used where only the factor rows matter
_OTHER_MEASURE_UNIT = "ZZCFGML"

# Reference doses carried by _SCTID_REF, in the substance's default unit.
_REF_MAXDOSE = 100.0
_REF_MAXDOSE_WEIGHT = 5.0
# the factor the tests convert through
_FACTOR = 2.0

_DRUGS_WITH_REFERENCE = [
    (_DRUG_CREATE, "ZZTest Medicamento Config"),
    (_DRUG_EXISTING, "ZZTest Medicamento Config Existente"),
    (_DRUG_UNITS, "ZZTest Medicamento Config Unidades"),
    (_DRUG_REFACTORED, "ZZTest Medicamento Config Refeito"),
    (_DRUG_DIVISION, "ZZTest Medicamento Config Divisor"),
    (_DRUG_MAXDOSE, "ZZTest Medicamento Config Dosemax"),
    (_DRUG_MAXDOSE_WEIGHT, "ZZTest Medicamento Config Dosemax Peso"),
    (_DRUG_V2, "ZZTest Medicamento Config V2"),
    (_DRUG_V2_UNITS, "ZZTest Medicamento Config V2 Unidades"),
    (_DRUG_REJECTED, "ZZTest Medicamento Config Recusado"),
]


@pytest.fixture(scope="module", autouse=True)
def setup_score_config_data(clean_test_artifacts):  # noqa: ARG001
    """Create the substances, drugs and measure units, after the global cleanup."""
    create_test_substance(_SCTID_REF, "ZZTest Substância Config", "mg")
    create_test_substance(_SCTID_PLAIN, "ZZTest Substância Config Sem Dose", "mg")

    session.execute(
        text(
            "UPDATE public.substancia SET dosemax_adulto = :maxdose,"
            " dosemax_peso_adulto = :maxdose_weight WHERE sctid = :sctid"
        ),
        {
            "maxdose": _REF_MAXDOSE,
            "maxdose_weight": _REF_MAXDOSE_WEIGHT,
            "sctid": _SCTID_REF,
        },
    )

    for unit in (_MEASURE_UNIT, _OTHER_MEASURE_UNIT):
        session.execute(
            text(
                "INSERT INTO demo.unidademedida"
                " (fkunidademedida, fkhospital, nome, unidademedida_nh)"
                " VALUES (:id, 1, :name, 'mg')"
                " ON CONFLICT (fkhospital, fkunidademedida) DO NOTHING"
            ),
            {"id": unit, "name": unit},
        )
    session_commit()

    for id_drug, name in _DRUGS_WITH_REFERENCE:
        create_test_drug(id_drug, name, _SCTID_REF)

    create_test_drug(
        _DRUG_NO_REFERENCE, "ZZTest Medicamento Config Sem Ref", _SCTID_PLAIN
    )

    yield

    # unidademedida/unidadeconverte are keyed by unit, not by the >= 90000 drug
    # window the shared cleanup wipes, so this module drops its own rows
    session.execute(
        text("DELETE FROM demo.unidadeconverte WHERE fkunidademedida = ANY(:ids)"),
        {"ids": [_MEASURE_UNIT, _OTHER_MEASURE_UNIT]},
    )
    session.execute(
        text("DELETE FROM demo.unidademedida WHERE fkunidademedida = ANY(:ids)"),
        {"ids": [_MEASURE_UNIT, _OTHER_MEASURE_UNIT]},
    )
    session_commit()


def _config(
    client,
    headers,
    id_drug: int,
    id_segment: int = _SEGMENT,
    v2: bool = False,
    **payload,
):
    """POST the config payload for one drug, defaulting to a valid v1 body."""
    body = {
        "idMeasureUnit": _MEASURE_UNIT,
        "division": None,
        "useWeight": False,
    }
    body.update(payload)

    url = f"{CONFIG_URL}/{id_segment}/{id_drug}"
    if v2:
        url = f"{url}/v2"

    return client.post(url, json=body, headers=headers)


def _read_attributes(id_drug: int, id_segment: int = _SEGMENT) -> DrugAttributes:
    """Return a fresh medatributos row (commit first to drop any snapshot)."""
    session_commit()
    return (
        session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == id_drug)
        .filter(DrugAttributes.idSegment == id_segment)
        .first()
    )


def _read_conversions(id_drug: int, id_segment: int = _SEGMENT) -> dict:
    """Return the drug's conversion factors for a segment, keyed by measure unit."""
    session_commit()
    return {
        c.idMeasureUnit: c.factor
        for c in session.query(MeasureUnitConvert)
        .filter(MeasureUnitConvert.idDrug == id_drug)
        .filter(MeasureUnitConvert.idSegment == id_segment)
        .all()
    }


def _audit_types(id_drug: int) -> list[int]:
    """Return the audit types recorded for a drug, oldest first."""
    session_commit()
    return [
        a.auditType
        for a in session.query(DrugAttributesAudit)
        .filter(DrugAttributesAudit.idDrug == id_drug)
        .order_by(DrugAttributesAudit.id)
        .all()
    ]


# ---------------------------------------------------------------------------
# payload guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", [None, ""])
def test_config_requires_a_measure_unit(client, config_manager_headers, missing):
    """POST config - a payload naming no measure unit is refused [400 BAD REQUEST]"""
    response = _config(
        client, config_manager_headers, _DRUG_REJECTED, idMeasureUnit=missing
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"


def test_config_rejects_a_division_of_one(client, config_manager_headers):
    """POST config - a divisor of 1 would produce a single range, so it is refused
    [400 BAD REQUEST]"""
    response = _config(client, config_manager_headers, _DRUG_REJECTED, division=1)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"


def test_config_rejects_an_unauthorized_segment(client, config_manager_headers):
    """POST config - the caller must be authorized on the segment
    [401 UNAUTHORIZED]"""
    response = _config(
        client,
        config_manager_headers,
        _DRUG_REJECTED,
        id_segment=_UNAUTHORIZED_SEGMENT,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.get_json()["code"] == "errors.businessRules"


def test_config_rejects_an_unknown_drug(client, config_manager_headers):
    """POST config - a drug with no medicamento row cannot be configured
    [400 BAD REQUEST]"""
    response = _config(client, config_manager_headers, _UNKNOWN_DRUG)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"


def test_config_requires_the_drug_attributes_permission(client, viewer_headers):
    """POST config - a role without WRITE_DRUG_ATTRIBUTES is refused
    [401 UNAUTHORIZED]"""
    response = _config(client, viewer_headers, _DRUG_REJECTED)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_a_refused_payload_writes_nothing(client, config_manager_headers):
    """POST config - a payload refused after the conversion factors were built
    rolls the whole request back, leaving no half-configured drug"""
    response = _config(
        client,
        config_manager_headers,
        _DRUG_REJECTED,
        id_segment=_UNAUTHORIZED_SEGMENT,
        measureUnitList=[{"idMeasureUnit": _MEASURE_UNIT, "fator": _FACTOR}],
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert _read_attributes(_DRUG_REJECTED, id_segment=_UNAUTHORIZED_SEGMENT) is None
    assert _read_conversions(_DRUG_REJECTED, id_segment=_UNAUTHORIZED_SEGMENT) == {}


# ---------------------------------------------------------------------------
# medatributos
# ---------------------------------------------------------------------------


def test_config_creates_the_attributes_from_the_substance_reference(
    client, config_manager_headers
):
    """POST config - a drug with no row for the segment gets one, built from its
    substance and stamped with the caller"""
    response = _config(
        client, config_manager_headers, _DRUG_CREATE, division=4, useWeight=True
    )

    assert response.status_code == status.HTTP_200_OK

    attributes = _read_attributes(_DRUG_CREATE)
    assert attributes is not None
    assert attributes.division == 4
    assert attributes.useWeight is True
    assert attributes.user == CALLER_ID
    # the reference row is written first, then the score-config update
    assert _audit_types(_DRUG_CREATE) == [
        DrugAttributesAuditTypeEnum.INSERT_FROM_REFERENCE.value,
        DrugAttributesAuditTypeEnum.UPSERT_BEFORE_GEN_SCORE.value,
    ]


def test_config_updates_the_existing_attributes_in_place(
    client, config_manager_headers
):
    """POST config - configuring the same drug twice updates its row instead of
    creating a second one"""
    _config(client, config_manager_headers, _DRUG_EXISTING, division=4, useWeight=True)
    _config(client, config_manager_headers, _DRUG_EXISTING, division=6, useWeight=False)

    session_commit()
    rows = (
        session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == _DRUG_EXISTING)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].division == 6
    assert rows[0].useWeight is False
    # only the first call had to build the row from the reference
    assert _audit_types(_DRUG_EXISTING) == [
        DrugAttributesAuditTypeEnum.INSERT_FROM_REFERENCE.value,
        DrugAttributesAuditTypeEnum.UPSERT_BEFORE_GEN_SCORE.value,
        DrugAttributesAuditTypeEnum.UPSERT_BEFORE_GEN_SCORE.value,
    ]


def test_config_stores_no_division_when_it_is_zero(client, config_manager_headers):
    """POST config - the screen sends 0 for "no ranges", which is stored as NULL
    so the score pipeline does not divide by it"""
    response = _config(client, config_manager_headers, _DRUG_DIVISION, division=0)

    assert response.status_code == status.HTTP_200_OK
    assert _read_attributes(_DRUG_DIVISION).division is None


# ---------------------------------------------------------------------------
# unidadeconverte
# ---------------------------------------------------------------------------


def test_config_saves_one_conversion_factor_per_listed_unit(
    client, config_manager_headers
):
    """POST config - every measureUnitList entry becomes a factor for the segment"""
    response = _config(
        client,
        config_manager_headers,
        _DRUG_UNITS,
        measureUnitList=[
            {"idMeasureUnit": _MEASURE_UNIT, "fator": _FACTOR},
            {"idMeasureUnit": _OTHER_MEASURE_UNIT, "fator": 0.5},
        ],
    )

    assert response.status_code == status.HTTP_200_OK
    assert _read_conversions(_DRUG_UNITS) == {
        _MEASURE_UNIT: _FACTOR,
        _OTHER_MEASURE_UNIT: 0.5,
    }
    # the factors belong to the configured segment only
    assert _read_conversions(_DRUG_UNITS, id_segment=2) == {}


def test_config_overwrites_a_factor_it_already_saved(client, config_manager_headers):
    """POST config - a corrected factor updates the existing row rather than
    adding a second one for the same unit"""
    _config(
        client,
        config_manager_headers,
        _DRUG_REFACTORED,
        measureUnitList=[{"idMeasureUnit": _MEASURE_UNIT, "fator": _FACTOR}],
    )
    _config(
        client,
        config_manager_headers,
        _DRUG_REFACTORED,
        measureUnitList=[{"idMeasureUnit": _MEASURE_UNIT, "fator": 10.0}],
    )

    assert _read_conversions(_DRUG_REFACTORED) == {_MEASURE_UNIT: 10.0}


# ---------------------------------------------------------------------------
# maximum dose
# ---------------------------------------------------------------------------


def test_config_converts_the_reference_max_dose_through_the_saved_factor(
    client, config_manager_headers
):
    """POST config - the substance's adult reference dose is converted with the
    factor saved in the same request and becomes the drug's dosemaxima"""
    response = _config(
        client,
        config_manager_headers,
        _DRUG_MAXDOSE,
        measureUnitList=[{"idMeasureUnit": _MEASURE_UNIT, "fator": _FACTOR}],
    )

    assert response.status_code == status.HTTP_200_OK

    attributes = _read_attributes(_DRUG_MAXDOSE)
    assert attributes.ref_maxdose == _REF_MAXDOSE * _FACTOR
    assert attributes.ref_maxdose_weight == _REF_MAXDOSE_WEIGHT * _FACTOR
    # useWeight is off, so the absolute reference is the one applied
    assert attributes.maxDose == _REF_MAXDOSE * _FACTOR


def test_config_applies_the_weight_reference_when_use_weight_is_set(
    client, config_manager_headers
):
    """POST config - with useWeight the dose per kilo is the one applied"""
    response = _config(
        client,
        config_manager_headers,
        _DRUG_MAXDOSE_WEIGHT,
        useWeight=True,
        measureUnitList=[{"idMeasureUnit": _MEASURE_UNIT, "fator": _FACTOR}],
    )

    assert response.status_code == status.HTTP_200_OK
    assert _read_attributes(_DRUG_MAXDOSE_WEIGHT).maxDose == (
        _REF_MAXDOSE_WEIGHT * _FACTOR
    )


def test_config_leaves_the_max_dose_empty_without_a_reference_dose(
    client, config_manager_headers
):
    """POST config - a substance carrying no reference dose cannot produce one,
    and the drug is left without a maximum"""
    response = _config(
        client,
        config_manager_headers,
        _DRUG_NO_REFERENCE,
        measureUnitList=[{"idMeasureUnit": _MEASURE_UNIT, "fator": _FACTOR}],
    )

    assert response.status_code == status.HTTP_200_OK

    attributes = _read_attributes(_DRUG_NO_REFERENCE)
    assert attributes.ref_maxdose is None
    assert attributes.maxDose is None


# ---------------------------------------------------------------------------
# /v2: the measure units are configured elsewhere
# ---------------------------------------------------------------------------


def test_config_v2_accepts_a_payload_without_a_measure_unit(
    client, config_manager_headers
):
    """POST config/v2 - the unit guard is dropped, so the division and weight
    flag can be saved on their own"""
    response = _config(
        client,
        config_manager_headers,
        _DRUG_V2,
        v2=True,
        idMeasureUnit=None,
        division=8,
        useWeight=True,
    )

    assert response.status_code == status.HTTP_200_OK

    attributes = _read_attributes(_DRUG_V2)
    assert attributes.division == 8
    assert attributes.useWeight is True
    assert _audit_types(_DRUG_V2)[-1] == (
        DrugAttributesAuditTypeEnum.UPSERT_BEFORE_GEN_SCORE.value
    )


def test_config_v2_does_not_write_the_conversion_factors(
    client, config_manager_headers
):
    """POST config/v2 - the unit screen owns unidadeconverte now, so a list sent
    to /v2 is ignored instead of being saved twice"""
    response = _config(
        client,
        config_manager_headers,
        _DRUG_V2_UNITS,
        v2=True,
        measureUnitList=[{"idMeasureUnit": _MEASURE_UNIT, "fator": _FACTOR}],
    )

    assert response.status_code == status.HTTP_200_OK
    assert _read_conversions(_DRUG_V2_UNITS) == {}


def test_config_v2_still_rejects_a_division_of_one(client, config_manager_headers):
    """POST config/v2 - skipping the unit guard does not skip the divisor one
    [400 BAD REQUEST]"""
    response = _config(
        client, config_manager_headers, _DRUG_REJECTED, v2=True, division=1
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"
