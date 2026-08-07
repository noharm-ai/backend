"""Unit tests for unit_conversion_service.get_unit_conversion_for_drug.

The function decides, for a single drug, which measure-unit conversion factors
to expose to the UI. Its logic is deterministic given two repository queries:

* the drug's configured default measure unit(s) (``medatributos``), and
* the list of possible conversions (one row per measure unit).

From those it computes three things per row: whether the row is the drug's
default unit, whether raw factors should be shown at all (``show_factors``),
and the ``factor`` value itself. It also synthesises a default row when the
substance's default unit is not already present in the conversion list.

These tests drive every branch by patching the two repository calls with
lightweight namespace rows — no database or request context is required. The
``@has_permission`` decorator is bypassed via ``__wrapped__`` so the business
logic is exercised directly.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from exception.validation_error import ValidationError
from models.enums import DefaultMeasureUnitEnum
from services import unit_conversion_service

# The undecorated business logic (skips the permission gate).
_get = unit_conversion_service.get_unit_conversion_for_drug.__wrapped__


def _conv_row(
    *,
    id=100,
    name="Dipirona",
    id_measure_unit,
    factor,
    description,
    measureunit_nh,
    default_measureunit,
):
    """Build a conversion-list row as returned by the repository query."""
    return SimpleNamespace(
        id=id,
        name=name,
        idMeasureUnit=id_measure_unit,
        factor=factor,
        description=description,
        measureunit_nh=measureunit_nh,
        default_measureunit=default_measureunit,
    )


def _configured_row(*, measureunit_nh):
    """Build a configured default-measure-unit row (medatributos)."""
    return SimpleNamespace(measureunit_nh=measureunit_nh)


def _run(configured, conversion_list, id_drug=100):
    """Invoke the function with both repository calls patched."""
    repo = unit_conversion_service.unit_conversion_repository
    with patch.object(
        repo,
        "get_drugattributes_default_measure_unit_for_drug",
        return_value=configured,
    ), patch.object(
        repo,
        "get_unit_conversion_for_drug",
        return_value=conversion_list,
    ):
        return _get(id_drug=id_drug)


class TestEmptyConversionList:
    """An empty conversion list is a business error."""

    def test_raises_validation_error(self):
        """No conversions available raises a 400 ValidationError."""
        with pytest.raises(ValidationError) as exc:
            _run(configured=[], conversion_list=[])
        assert exc.value.httpStatus == 400
        assert exc.value.code == "errors.businessRules"


class TestFactorSelection:
    """Per-row factor selection across the default / show_factors branches."""

    def test_default_row_gets_factor_one(self):
        """The row matching the substance default unit is marked default, factor 1."""
        rows = [
            _conv_row(
                id_measure_unit=1,
                factor=0.5,
                description="milligram",
                measureunit_nh="mg",
                default_measureunit="mg",
            ),
        ]
        result = _run(configured=[], conversion_list=rows)

        assert result["substanceMeasureUnit"] == "mg"
        assert len(result["conversionList"]) == 1
        row = result["conversionList"][0]
        assert row["default"] is True
        assert row["factor"] == 1
        assert row["id"] == "100-1"
        assert row["measureUnit"] == "milligram"

    def test_non_default_shows_factor_when_show_factors_true(self):
        """With no configured override, non-default rows expose their raw factor."""
        rows = [
            _conv_row(
                id_measure_unit=1,
                factor=1,
                description="milligram",
                measureunit_nh="mg",
                default_measureunit="mg",
            ),
            _conv_row(
                id_measure_unit=2,
                factor=1000,
                description="gram",
                measureunit_nh="g",
                default_measureunit="mg",
            ),
        ]
        result = _run(configured=[], conversion_list=rows)

        by_unit = {r["drugMeasureUnitNh"]: r for r in result["conversionList"]}
        assert by_unit["mg"]["factor"] == 1
        assert by_unit["mg"]["default"] is True
        assert by_unit["g"]["factor"] == 1000
        assert by_unit["g"]["default"] is False

    def test_multiple_configured_units_hide_factors(self):
        """More than one configured unit forces non-default factors to None."""
        rows = [
            _conv_row(
                id_measure_unit=1,
                factor=1,
                description="milligram",
                measureunit_nh="mg",
                default_measureunit="mg",
            ),
            _conv_row(
                id_measure_unit=2,
                factor=1000,
                description="gram",
                measureunit_nh="g",
                default_measureunit="mg",
            ),
        ]
        configured = [
            _configured_row(measureunit_nh="mg"),
            _configured_row(measureunit_nh="g"),
        ]
        result = _run(configured=configured, conversion_list=rows)

        by_unit = {r["drugMeasureUnitNh"]: r for r in result["conversionList"]}
        # default row still forced to 1 regardless of show_factors
        assert by_unit["mg"]["factor"] == 1
        # non-default hidden because show_factors is False
        assert by_unit["g"]["factor"] is None

    def test_single_matching_configured_unit_keeps_factors(self):
        """One configured unit equal to the default keeps show_factors on."""
        rows = [
            _conv_row(
                id_measure_unit=1,
                factor=1,
                description="milligram",
                measureunit_nh="mg",
                default_measureunit="mg",
            ),
            _conv_row(
                id_measure_unit=2,
                factor=1000,
                description="gram",
                measureunit_nh="g",
                default_measureunit="mg",
            ),
        ]
        configured = [_configured_row(measureunit_nh="mg")]
        result = _run(configured=configured, conversion_list=rows)

        by_unit = {r["drugMeasureUnitNh"]: r for r in result["conversionList"]}
        assert by_unit["g"]["factor"] == 1000

    def test_single_mismatching_configured_unit_hides_factors(self):
        """One configured unit different from the default turns show_factors off."""
        rows = [
            _conv_row(
                id_measure_unit=1,
                factor=1,
                description="milligram",
                measureunit_nh="mg",
                default_measureunit="mg",
            ),
            _conv_row(
                id_measure_unit=2,
                factor=1000,
                description="gram",
                measureunit_nh="g",
                default_measureunit="mg",
            ),
        ]
        configured = [_configured_row(measureunit_nh="g")]
        result = _run(configured=configured, conversion_list=rows)

        by_unit = {r["drugMeasureUnitNh"]: r for r in result["conversionList"]}
        assert by_unit["g"]["factor"] is None


class TestSubstanceUnitFallback:
    """When the substance has no default unit it falls back to 'un'."""

    def test_none_default_falls_back_to_un_and_hides_factors(self):
        """A null substance default becomes 'un' with factors hidden."""
        rows = [
            _conv_row(
                id_measure_unit=1,
                factor=500,
                description="milligram",
                measureunit_nh="mg",
                default_measureunit=None,
            ),
        ]
        result = _run(configured=[], conversion_list=rows)

        assert result["substanceMeasureUnit"] == DefaultMeasureUnitEnum.UN.value
        # the mg row is not the default (un != mg) and factors are hidden
        first = result["conversionList"][0]
        assert first["drugMeasureUnitNh"] == "mg"
        assert first["default"] is False
        assert first["factor"] is None


class TestSyntheticDefaultRow:
    """A default row is appended when the substance unit is absent from the list."""

    def test_synthetic_default_appended_when_absent(self):
        """If no row is the default unit, a synthetic default row is added."""
        rows = [
            _conv_row(
                id_measure_unit=2,
                factor=1000,
                description="gram",
                measureunit_nh="g",
                default_measureunit="mg",
            ),
        ]
        result = _run(configured=[], conversion_list=rows, id_drug=100)

        defaults = [r for r in result["conversionList"] if r["default"]]
        assert len(defaults) == 1
        synth = defaults[0]
        assert synth["drugMeasureUnitNh"] == "mg"
        assert synth["idMeasureUnit"] == "mg"
        assert synth["factor"] == 1
        assert synth["id"] == "100-mg"

    def test_no_synthetic_row_when_default_present(self):
        """When a real default row exists, no synthetic row is appended."""
        rows = [
            _conv_row(
                id_measure_unit=1,
                factor=1,
                description="milligram",
                measureunit_nh="mg",
                default_measureunit="mg",
            ),
        ]
        result = _run(configured=[], conversion_list=rows)

        assert len(result["conversionList"]) == 1
        assert result["conversionList"][0]["default"] is True


class TestEnvelope:
    """The returned envelope echoes the drug identity."""

    def test_envelope_fields(self):
        """name and idDrug come from the first conversion row."""
        rows = [
            _conv_row(
                id=100,
                name="Dipirona",
                id_measure_unit=1,
                factor=1,
                description="milligram",
                measureunit_nh="mg",
                default_measureunit="mg",
            ),
        ]
        result = _run(configured=[], conversion_list=rows)

        assert result["name"] == "Dipirona"
        assert result["idDrug"] == 100
        assert result["substanceMeasureUnit"] == "mg"
        assert isinstance(result["conversionList"], list)
