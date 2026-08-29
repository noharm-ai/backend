"""Integration tests for the write half of the drug unit-conversion feature.

``GET /drugs/unit-conversion/<drug>`` is covered by
``tests/unit/test_unit_conversion_service.py``, but the two endpoints that
actually change data had no coverage at all:

* ``POST /drugs/unit-conversion/<drug>`` — the curator screen that fixes a
  drug's conversion factors. It is deceptively wide: the payload names no
  segment, yet the save is applied to *every* segment, creating the
  ``medatributos`` row from the substance reference where one is missing,
  pinning each row's default measure unit and upserting one
  ``unidadeconverte`` row per segment/unit pair. The default unit comes from
  the substance and falls back to ``un``; when that unit has no
  ``unidademedida`` row yet, the save creates it.
* ``POST /drugs/process-scores/<drug>`` — hands the drug to the score Lambda.

Both AWS calls are stubbed: the save path must *not* reach Lambda (it passes
``skip_lambda``), and the score path is asserted on the payload it sends,
which is the part the backend decides.

Each test saves against its own drug, so the module has no internal ordering.
Fixtures use the reserved ``>= 90000`` id range (90400 block) so the
session-scoped ``clean_test_artifacts`` fixture removes them. Measure units
are not in that range, so this module removes the ones it created itself.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from models.appendix import MeasureUnit, MeasureUnitConvert
from models.enums import DefaultMeasureUnitEnum
from models.main import DrugAttributes
from models.segment import Segment
from tests.conftest import session, session_commit
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_substance,
)
from utils import status

SAVE_URL = "/drugs/unit-conversion"
SCORES_URL = "/drugs/process-scores"

# Ids reserved for this module (90400 block, distinct from other modules').
_SCTID_WITH_DEFAULT = 90401
_SCTID_WITHOUT_DEFAULT = 90402

_DRUG_SEGMENTS = 90401  # asserts the conversions reach every segment
_DRUG_ATTRIBUTES = 90402  # asserts medatributos is created on the fly
_DRUG_MEASURE_UNIT = 90403  # asserts the default unit row is created
_DRUG_RESAVED = 90404  # saved twice, asserts the upsert
_DRUG_WITHOUT_DEFAULT = 90405  # substance names no unit, so ``un`` is used
_DRUG_NO_LAMBDA = 90406  # asserts the save stays local
_DRUG_SCORES = 90407  # target of the score endpoint
_DRUG_REJECTED = 90408  # receives the payloads that must be refused
_UNKNOWN_DRUG = 90499

# A default measure unit absent from the seed, so the save has to create it.
_TEST_MEASURE_UNIT = "ZZTESTUN"

# an existing seed unit, used as the converted-from unit
_SEED_MEASURE_UNIT = "1"

# the demo user behind the config_manager_headers fixture
CALLER_ID = 1
CALLER_SCHEMA = "demo"

_DRUGS_WITH_DEFAULT = [
    (_DRUG_SEGMENTS, "ZZTest Medicamento Segmentos"),
    (_DRUG_ATTRIBUTES, "ZZTest Medicamento Atributos UC"),
    (_DRUG_MEASURE_UNIT, "ZZTest Medicamento Unidade"),
    (_DRUG_RESAVED, "ZZTest Medicamento Refeito"),
    (_DRUG_NO_LAMBDA, "ZZTest Medicamento Sem Lambda"),
    (_DRUG_SCORES, "ZZTest Medicamento Escores"),
    (_DRUG_REJECTED, "ZZTest Medicamento Recusado"),
]


@pytest.fixture(scope="module", autouse=True)
def setup_unit_conversion_data(clean_test_artifacts):  # noqa: ARG001
    """Create the substances and drugs for this module, after the global cleanup.

    ``unidademedida`` rows fall outside the ``>= 90000`` window the shared
    cleanup wipes, so whatever the save creates is removed here on teardown —
    identified by diffing against the units present before the tests ran.
    """
    create_test_substance(
        _SCTID_WITH_DEFAULT, "ZZTest Substância Unidade", _TEST_MEASURE_UNIT
    )
    create_test_substance(_SCTID_WITHOUT_DEFAULT, "ZZTest Substância Sem Unidade", None)

    for id_drug, name in _DRUGS_WITH_DEFAULT:
        create_test_drug(id_drug, name, _SCTID_WITH_DEFAULT)

    create_test_drug(
        _DRUG_WITHOUT_DEFAULT, "ZZTest Medicamento Sem Unidade", _SCTID_WITHOUT_DEFAULT
    )

    preexisting_units = _measure_unit_ids()

    yield

    created_units = _measure_unit_ids() - preexisting_units
    if created_units:
        session.execute(
            text("DELETE FROM demo.unidademedida WHERE fkunidademedida = ANY(:ids)"),
            {"ids": list(created_units)},
        )
        session_commit()


def _measure_unit_ids() -> set:
    """Every measure unit id currently configured in the demo schema."""
    session_commit()

    return {row.id for row in session.query(MeasureUnit).all()}


def _segments() -> list:
    """All segments the save is expected to touch."""
    return session.query(Segment).order_by(Segment.id).all()


def _save(client, headers, id_drug, conversion_list):
    """POST a conversion list, with Lambda stubbed so nothing leaves the process."""
    with patch("services.unit_conversion_service.aws.get_client") as get_client:
        response = client.post(
            f"{SAVE_URL}/{id_drug}",
            data=json.dumps({"conversion_list": conversion_list}),
            headers=headers,
        )

    return response, get_client


def _conversions(id_drug: int) -> dict:
    """Saved factors for a drug, keyed by (segment, measure unit)."""
    session_commit()  # see the rows the request committed

    rows = (
        session.query(MeasureUnitConvert)
        .filter(MeasureUnitConvert.idDrug == id_drug)
        .all()
    )

    return {(r.idSegment, r.idMeasureUnit): r.factor for r in rows}


def _attributes(id_drug: int) -> dict:
    """Saved medatributos rows for a drug, keyed by segment."""
    session_commit()

    rows = session.query(DrugAttributes).filter(DrugAttributes.idDrug == id_drug).all()

    return {r.idSegment: r for r in rows}


def test_save_applies_the_conversions_to_every_segment(client, config_manager_headers):
    """One payload, no segment in it, and every segment ends up converted [200]."""
    response, _ = _save(
        client,
        config_manager_headers,
        _DRUG_SEGMENTS,
        [
            {"id_measure_unit": _TEST_MEASURE_UNIT, "factor": 1},
            {"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 0.5},
        ],
    )

    assert response.status_code == status.HTTP_200_OK

    segments = _segments()
    assert response.get_json()["data"]["updated"] == [s.description for s in segments]

    saved = _conversions(_DRUG_SEGMENTS)
    assert set(saved) == {
        (segment.id, unit)
        for segment in segments
        for unit in (_TEST_MEASURE_UNIT, _SEED_MEASURE_UNIT)
    }
    for segment in segments:
        assert saved[(segment.id, _TEST_MEASURE_UNIT)] == 1
        assert saved[(segment.id, _SEED_MEASURE_UNIT)] == 0.5


def test_save_creates_the_drug_attributes_it_needs(client, config_manager_headers):
    """The drug has no medatributos row anywhere; the save creates one per segment [200]."""
    assert _attributes(_DRUG_ATTRIBUTES) == {}

    _save(
        client,
        config_manager_headers,
        _DRUG_ATTRIBUTES,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 1}],
    )

    attributes = _attributes(_DRUG_ATTRIBUTES)

    assert set(attributes) == {s.id for s in _segments()}
    for record in attributes.values():
        # the substance's unit becomes the segment's default measure unit
        assert record.idMeasureUnit == _TEST_MEASURE_UNIT
        assert record.user == CALLER_ID


def test_save_creates_the_missing_default_measure_unit(client, config_manager_headers):
    """A substance may name a unit the schema does not configure yet [200]."""
    session.execute(
        text("DELETE FROM demo.unidademedida WHERE fkunidademedida = :id"),
        {"id": _TEST_MEASURE_UNIT},
    )
    session_commit()

    _save(
        client,
        config_manager_headers,
        _DRUG_MEASURE_UNIT,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 1}],
    )
    session_commit()

    unit = (
        session.query(MeasureUnit).filter(MeasureUnit.id == _TEST_MEASURE_UNIT).first()
    )

    assert unit is not None
    assert unit.description == _TEST_MEASURE_UNIT
    assert unit.measureunit_nh == _TEST_MEASURE_UNIT


def test_resaving_updates_the_factor_instead_of_duplicating(
    client, config_manager_headers
):
    """The upsert is keyed by segment/drug/unit, so a second save overwrites [200]."""
    _save(
        client,
        config_manager_headers,
        _DRUG_RESAVED,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 2}],
    )

    first = _conversions(_DRUG_RESAVED)
    assert set(first.values()) == {2}

    response, _ = _save(
        client,
        config_manager_headers,
        _DRUG_RESAVED,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 7.5}],
    )
    assert response.status_code == status.HTTP_200_OK

    second = _conversions(_DRUG_RESAVED)
    assert set(second) == set(first)
    assert set(second.values()) == {7.5}


def test_substance_without_default_unit_falls_back_to_un(
    client, config_manager_headers
):
    """No curated unit on the substance means the generic ``un`` is used [200]."""
    response, _ = _save(
        client,
        config_manager_headers,
        _DRUG_WITHOUT_DEFAULT,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 3}],
    )

    assert response.status_code == status.HTTP_200_OK

    fallback = DefaultMeasureUnitEnum.UN.value
    attributes = _attributes(_DRUG_WITHOUT_DEFAULT)
    assert attributes
    for record in attributes.values():
        assert record.idMeasureUnit == fallback

    assert session.query(MeasureUnit).filter(MeasureUnit.id == fallback).first()


def test_save_does_not_invoke_the_score_lambda(client, config_manager_headers):
    """Scores are generated by a separate call, so the save must stay local [200]."""
    response, get_client = _save(
        client,
        config_manager_headers,
        _DRUG_NO_LAMBDA,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 4}],
    )

    assert response.status_code == status.HTTP_200_OK
    get_client.assert_not_called()


@pytest.mark.parametrize(
    "conversion_list",
    [[], [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 0}]],
    ids=["empty list", "zero factor"],
)
def test_save_rejects_a_conversion_list_it_cannot_apply(
    client, config_manager_headers, conversion_list
):
    """A missing list or a zero factor would silently break dose conversion [400]."""
    response, _ = _save(client, config_manager_headers, _DRUG_REJECTED, conversion_list)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"
    assert _conversions(_DRUG_REJECTED) == {}


def test_save_rejects_a_non_numeric_factor(client, config_manager_headers):
    """The factor is typed, so a text value never reaches the service [400]."""
    response, _ = _save(
        client,
        config_manager_headers,
        _DRUG_REJECTED,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": "muito"}],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["validations"]
    assert _conversions(_DRUG_REJECTED) == {}


def test_save_rejects_an_unknown_drug(client, config_manager_headers):
    """There is no drug to build the attributes from, so nothing is written [400]."""
    response, _ = _save(
        client,
        config_manager_headers,
        _UNKNOWN_DRUG,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 1}],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"
    assert _conversions(_UNKNOWN_DRUG) == {}
    assert _attributes(_UNKNOWN_DRUG) == {}


def test_role_without_write_drug_attributes_cannot_save(client, analyst_headers):
    """PRESCRIPTION_ANALYST may read conversions but never write them [401]."""
    response, _ = _save(
        client,
        analyst_headers,
        _DRUG_REJECTED,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 1}],
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert _conversions(_DRUG_REJECTED) == {}


def test_process_scores_hands_the_drug_to_the_lambda(client, config_manager_headers):
    """The score request carries the caller's schema and user, not just the drug [200]."""
    lambda_client = MagicMock()
    lambda_client.invoke.return_value = {
        "ResponseMetadata": {"RequestId": "zztest-request-id"},
        "StatusCode": 202,
    }

    with patch(
        "services.unit_conversion_service.aws.get_client", return_value=lambda_client
    ):
        response = client.post(
            f"{SCORES_URL}/{_DRUG_SCORES}", headers=config_manager_headers
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == {
        "request_id": "zztest-request-id",
        "status_code": 202,
    }

    payload = json.loads(lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload == {
        "command": "lambda_scores.process_drug_scores",
        "schema": CALLER_SCHEMA,
        "id_user": CALLER_ID,
        "id_drug": _DRUG_SCORES,
    }
    # fire and forget: the caller polls the scores, it does not wait here
    assert lambda_client.invoke.call_args.kwargs["InvocationType"] == "Event"


def test_process_scores_requires_write_drug_attributes(client, analyst_headers):
    """Regenerating scores is a curation action, closed to the analyst role [401]."""
    with patch("services.unit_conversion_service.aws.get_client") as get_client:
        response = client.post(f"{SCORES_URL}/{_DRUG_SCORES}", headers=analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    get_client.assert_not_called()
