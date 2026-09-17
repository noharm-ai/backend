"""Integration tests for the read half of the drug unit-conversion feature.

``GET /drugs/unit-conversion/<drug>`` feeds the curator screen that fixes a
drug's conversion factors: it lists every measure unit the drug could be
converted from, the factor already recorded for each, and which one is the
drug's default. ``tests/unit/test_unit_conversion_service.py`` drives the
service's decision table with the two repository calls patched out, so the
queries behind them had never run — and they are where the feature's real
complexity lives:

* ``_build_units_cte`` unions three independent sources of measure units —
  what the drug was actually prescribed in (``prescricaoagg``), what is
  already converted (``unidadeconverte``) and the unit its price is expressed
  in (``medatributos.fkunidademedidacusto``) — discarding blank ids from each;
* the conversion query then folds the per-segment ``unidadeconverte`` rows
  into one factor per unit by taking the lowest, because the screen saves a
  single factor back to every segment;
* ``get_drugattributes_default_measure_unit_for_drug`` groups the configured
  default units, which is what decides whether raw factors may be shown at
  all.

These tests exercise that SQL end to end, then assert the response the curator
screen actually renders. Both permissions the endpoint accepts are covered:
``WRITE_DRUG_ATTRIBUTES`` (the curator) and ``TRAINING_RECORDING`` (the user
who records the training videos).

Fixtures use the reserved ``>= 90000`` id range (90800 block, distinct from
other modules') so the session-scoped ``clean_test_artifacts`` fixture removes
them. Measure units are keyed by text and fall outside that window, so this
module deletes the ones it creates itself.
"""

import pytest
from sqlalchemy import text

from models.enums import DefaultMeasureUnitEnum
from tests.conftest import session, session_commit
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_substance,
)
from utils import status

READ_URL = "/drugs/unit-conversion"

# Measure units created by this module. ``unidademedida_nh`` is the value the
# substance's default unit is compared against; every seed unit leaves it NULL,
# so the module needs its own to exercise the match at all.
_UNIT_DEFAULT = "ZZTESTUCMG"
_UNIT_PRESCRIBED = "ZZTESTUCML"
_UNIT_CONVERTED = "ZZTESTUCUI"
_UNIT_PRICE = "ZZTESTUCGT"
_TEST_UNITS = (_UNIT_DEFAULT, _UNIT_PRESCRIBED, _UNIT_CONVERTED, _UNIT_PRICE)

# Ids reserved for this module (90800 block).
_SCTID_WITH_DEFAULT = 90801
_SCTID_WITHOUT_DEFAULT = 90802

_DRUG_SOURCES = 90801  # one unit from each of the three sources
_DRUG_SEGMENT_FACTORS = 90802  # same unit converted differently per segment
_DRUG_DEFAULT_MISSING = 90803  # default unit absent from the conversion list
_DRUG_UNIT_MISMATCH = 90804  # configured unit disagrees with the substance
_DRUG_TWO_UNITS = 90805  # two different units configured across segments
_DRUG_NO_SUBSTANCE_UNIT = 90806  # substance names no default unit
_DRUG_BLANK_UNITS = 90807  # only blank/NULL unit ids anywhere
_DRUG_PERMISSIONS = 90808  # target of the permission checks
_UNKNOWN_DRUG = 90899

# Both segments in the demo schema; the per-segment fold is only visible
# because the seed has more than one.
_SEGMENT_A = 1
_SEGMENT_B = 2


@pytest.fixture(scope="module", autouse=True)
def setup_unit_conversion_read_data(clean_test_artifacts):  # noqa: ARG001
    """Create the units, substances and drugs this module reads back.

    Runs after the global cleanup so the ``>= 90000`` rows it inserts survive
    the whole module. ``unidademedida`` rows are outside that window, so they
    are removed here.
    """
    _delete_test_measure_units()

    for unit in _TEST_UNITS:
        session.execute(
            text(
                "INSERT INTO demo.unidademedida "
                "(fkunidademedida, fkhospital, nome, unidademedida_nh) "
                "VALUES (:unit, 1, :description, :unit)"
            ),
            {"unit": unit, "description": f"Unidade {unit}"},
        )
    session_commit()

    create_test_substance(
        _SCTID_WITH_DEFAULT, "ZZTest Substância Conversão", _UNIT_DEFAULT
    )
    create_test_substance(
        _SCTID_WITHOUT_DEFAULT, "ZZTest Substância Conversão Sem Unidade", None
    )

    for id_drug in (
        _DRUG_SOURCES,
        _DRUG_SEGMENT_FACTORS,
        _DRUG_DEFAULT_MISSING,
        _DRUG_UNIT_MISMATCH,
        _DRUG_TWO_UNITS,
        _DRUG_BLANK_UNITS,
        _DRUG_PERMISSIONS,
    ):
        create_test_drug(
            id_drug, f"ZZTest Medicamento UC {id_drug}", _SCTID_WITH_DEFAULT
        )

    create_test_drug(
        _DRUG_NO_SUBSTANCE_UNIT,
        f"ZZTest Medicamento UC {_DRUG_NO_SUBSTANCE_UNIT}",
        _SCTID_WITHOUT_DEFAULT,
    )

    _seed_conversion_sources()

    yield

    _delete_test_measure_units()


def _delete_test_measure_units():
    """Drop the measure units this module owns, by their reserved prefix."""
    session.execute(
        text("DELETE FROM demo.unidademedida WHERE fkunidademedida = ANY(:units)"),
        {"units": list(_TEST_UNITS)},
    )
    session_commit()


def _prescribed(id_drug: int, unit, segment: int = _SEGMENT_A, dose: float = 10):
    """Record that the drug was prescribed in ``unit`` (``prescricaoagg``)."""
    session.execute(
        text(
            "INSERT INTO demo.prescricaoagg "
            "(fkhospital, fksetor, idsegmento, fkmedicamento, fkunidademedida, "
            "fkfrequencia, dose, contagem) "
            "VALUES (1, :segment, :segment, :drug, :unit, '1', :dose, 5)"
        ),
        {"segment": segment, "drug": id_drug, "unit": unit, "dose": dose},
    )


def _converted(id_drug: int, unit: str, factor: float, segment: int = _SEGMENT_A):
    """Record an existing conversion factor (``unidadeconverte``)."""
    session.execute(
        text(
            "INSERT INTO demo.unidadeconverte "
            "(idsegmento, fkmedicamento, fkunidademedida, fator) "
            "VALUES (:segment, :drug, :unit, :factor)"
        ),
        {"segment": segment, "drug": id_drug, "unit": unit, "factor": factor},
    )


def _attributes(id_drug: int, segment: int, *, unit=None, price_unit=None):
    """Configure the drug's default and/or price unit (``medatributos``)."""
    session.execute(
        text(
            "INSERT INTO demo.medatributos "
            "(fkmedicamento, idsegmento, fkunidademedida, fkunidademedidacusto) "
            "VALUES (:drug, :segment, :unit, :price_unit)"
        ),
        {
            "drug": id_drug,
            "segment": segment,
            "unit": unit,
            "price_unit": price_unit,
        },
    )


def _seed_conversion_sources():
    """Give every drug the unit rows its test reads back."""
    # one unit per source, so the union has to reach all three tables
    _prescribed(_DRUG_SOURCES, _UNIT_PRESCRIBED)
    _converted(_DRUG_SOURCES, _UNIT_CONVERTED, 0.25)
    _attributes(_DRUG_SOURCES, _SEGMENT_A, price_unit=_UNIT_PRICE)

    # the same unit converted differently in each segment
    _converted(_DRUG_SEGMENT_FACTORS, _UNIT_PRESCRIBED, 4, segment=_SEGMENT_A)
    _converted(_DRUG_SEGMENT_FACTORS, _UNIT_PRESCRIBED, 0.5, segment=_SEGMENT_B)

    # nothing points at the substance's default unit
    _prescribed(_DRUG_DEFAULT_MISSING, _UNIT_PRESCRIBED)
    _converted(_DRUG_DEFAULT_MISSING, _UNIT_PRESCRIBED, 3)

    # configured default unit is not the substance's
    _prescribed(_DRUG_UNIT_MISMATCH, _UNIT_PRESCRIBED)
    _converted(_DRUG_UNIT_MISMATCH, _UNIT_PRESCRIBED, 7)
    _converted(_DRUG_UNIT_MISMATCH, _UNIT_DEFAULT, 1)
    _attributes(_DRUG_UNIT_MISMATCH, _SEGMENT_A, unit=_UNIT_CONVERTED)

    # two segments configured with different default units
    _prescribed(_DRUG_TWO_UNITS, _UNIT_PRESCRIBED)
    _converted(_DRUG_TWO_UNITS, _UNIT_PRESCRIBED, 9)
    _converted(_DRUG_TWO_UNITS, _UNIT_DEFAULT, 1)
    _attributes(_DRUG_TWO_UNITS, _SEGMENT_A, unit=_UNIT_DEFAULT)
    _attributes(_DRUG_TWO_UNITS, _SEGMENT_B, unit=_UNIT_CONVERTED)

    # substance names no default unit at all
    _prescribed(_DRUG_NO_SUBSTANCE_UNIT, _UNIT_PRESCRIBED)
    _converted(_DRUG_NO_SUBSTANCE_UNIT, _UNIT_PRESCRIBED, 6)

    # only unusable unit ids: the union must discard all of them
    _prescribed(_DRUG_BLANK_UNITS, "", dose=11)
    _prescribed(_DRUG_BLANK_UNITS, None, dose=12)
    _attributes(_DRUG_BLANK_UNITS, _SEGMENT_A, price_unit="")

    _prescribed(_DRUG_PERMISSIONS, _UNIT_PRESCRIBED)

    session_commit()


def _read(client, headers, id_drug):
    """GET the conversion list for a drug."""
    return client.get(f"{READ_URL}/{id_drug}", headers=headers)


def _data(response):
    """The payload of a successful response envelope."""
    return response.get_json()["data"]


def _by_unit(response) -> dict:
    """The returned conversion list, indexed by measure unit."""
    return {row["idMeasureUnit"]: row for row in _data(response)["conversionList"]}


def test_conversion_list_unions_every_source_of_measure_units(
    client, config_manager_headers
):
    """Prescribed, already-converted and price units are offered together [200]."""
    response = _read(client, config_manager_headers, _DRUG_SOURCES)

    assert response.status_code == status.HTTP_200_OK

    data = _data(response)
    assert data["idDrug"] == _DRUG_SOURCES
    assert data["name"] == f"ZZTest Medicamento UC {_DRUG_SOURCES}"
    assert data["substanceMeasureUnit"] == _UNIT_DEFAULT

    by_unit = _by_unit(response)
    # one unit from prescricaoagg, one from unidadeconverte, one from the
    # price column — plus the substance default, appended because no source
    # named it
    assert set(by_unit) == {
        _UNIT_PRESCRIBED,
        _UNIT_CONVERTED,
        _UNIT_PRICE,
        _UNIT_DEFAULT,
    }
    # each row carries the unit's description and the id the save posts back
    assert by_unit[_UNIT_CONVERTED]["measureUnit"] == f"Unidade {_UNIT_CONVERTED}"
    assert by_unit[_UNIT_CONVERTED]["id"] == f"{_DRUG_SOURCES}-{_UNIT_CONVERTED}"


def test_recorded_factor_is_returned_and_missing_ones_stay_empty(
    client, config_manager_headers
):
    """A unit with no unidadeconverte row has no factor to show yet [200]."""
    by_unit = _by_unit(_read(client, config_manager_headers, _DRUG_SOURCES))

    assert by_unit[_UNIT_CONVERTED]["factor"] == 0.25
    # offered by the union, but never converted
    assert by_unit[_UNIT_PRESCRIBED]["factor"] is None
    assert by_unit[_UNIT_PRICE]["factor"] is None


def test_lowest_factor_across_segments_is_the_one_offered(
    client, config_manager_headers
):
    """The screen saves one factor per unit, so the segments are folded [200]."""
    by_unit = _by_unit(_read(client, config_manager_headers, _DRUG_SEGMENT_FACTORS))

    # 4 in one segment and 0.5 in the other collapse to the minimum
    assert by_unit[_UNIT_PRESCRIBED]["factor"] == 0.5


def test_substance_default_unit_is_flagged_and_pinned_to_one(
    client, config_manager_headers
):
    """Converting the default unit into itself is always a factor of 1 [200]."""
    by_unit = _by_unit(_read(client, config_manager_headers, _DRUG_SOURCES))

    assert by_unit[_UNIT_DEFAULT]["default"] is True
    assert by_unit[_UNIT_DEFAULT]["factor"] == 1
    # every other unit is a conversion source, not the default
    assert not any(
        row["default"] for unit, row in by_unit.items() if unit != _UNIT_DEFAULT
    )


def test_default_unit_is_appended_when_no_source_names_it(
    client, config_manager_headers
):
    """The curator still needs the default row to convert towards [200]."""
    response = _read(client, config_manager_headers, _DRUG_DEFAULT_MISSING)

    assert response.status_code == status.HTTP_200_OK

    by_unit = _by_unit(response)
    assert set(by_unit) == {_UNIT_PRESCRIBED, _UNIT_DEFAULT}

    appended = by_unit[_UNIT_DEFAULT]
    assert appended["default"] is True
    assert appended["factor"] == 1
    # synthesised rather than read back, so it is labelled by its own id
    assert appended["measureUnit"] == _UNIT_DEFAULT
    assert appended["id"] == f"{_DRUG_DEFAULT_MISSING}-{_UNIT_DEFAULT}"


def test_factors_are_hidden_when_the_configured_unit_is_not_the_default(
    client, config_manager_headers
):
    """Stored factors mean nothing against a different base unit [200]."""
    by_unit = _by_unit(_read(client, config_manager_headers, _DRUG_UNIT_MISMATCH))

    # the default still converts into itself...
    assert by_unit[_UNIT_DEFAULT]["default"] is True
    assert by_unit[_UNIT_DEFAULT]["factor"] == 1
    # ...but the recorded 7 is withheld until the drug is configured correctly
    assert by_unit[_UNIT_PRESCRIBED]["factor"] is None


def test_factors_are_hidden_when_segments_disagree_on_the_unit(
    client, config_manager_headers
):
    """More than one configured unit makes the stored factors ambiguous [200]."""
    by_unit = _by_unit(_read(client, config_manager_headers, _DRUG_TWO_UNITS))

    assert by_unit[_UNIT_DEFAULT]["factor"] == 1
    assert by_unit[_UNIT_PRESCRIBED]["factor"] is None


def test_substance_without_default_unit_falls_back_to_un(
    client, config_manager_headers
):
    """With no curated unit there is no base to trust, so factors stay empty [200]."""
    response = _read(client, config_manager_headers, _DRUG_NO_SUBSTANCE_UNIT)

    assert response.status_code == status.HTTP_200_OK

    fallback = DefaultMeasureUnitEnum.UN.value
    assert _data(response)["substanceMeasureUnit"] == fallback

    by_unit = _by_unit(response)
    assert by_unit[fallback]["default"] is True
    assert by_unit[fallback]["factor"] == 1
    assert by_unit[_UNIT_PRESCRIBED]["factor"] is None


def test_blank_measure_units_are_not_offered(client, config_manager_headers):
    """Empty and NULL unit ids are noise from the integration, never options [400]."""
    response = _read(client, config_manager_headers, _DRUG_BLANK_UNITS)

    # discarding them leaves nothing to convert, which is the error case
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"


def test_drug_without_any_measure_unit_is_rejected(client, config_manager_headers):
    """A drug never prescribed, converted or priced has nothing to offer [400]."""
    response = _read(client, config_manager_headers, _UNKNOWN_DRUG)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"


def test_training_role_can_read_the_conversions(client, training_headers):
    """TRAINING_RECORDING is the endpoint's second accepted permission [200]."""
    response = _read(client, training_headers, _DRUG_PERMISSIONS)

    assert response.status_code == status.HTTP_200_OK
    assert _by_unit(response)[_UNIT_PRESCRIBED]["factor"] is None


def test_role_without_drug_attribute_permission_cannot_read(client, analyst_headers):
    """PRESCRIPTION_ANALYST does not curate drugs, so the list is closed [401]."""
    response = _read(client, analyst_headers, _DRUG_PERMISSIONS)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
