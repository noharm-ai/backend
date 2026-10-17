"""Unit tests for the admin max-dose reference calculation (services.admin.admin_drug_service).

``get_max_dose_ref`` turns a substance's reference max dose — always expressed in
the substance's own default measure unit — into a max dose expressed in the
unit the drug is prescribed in. It needs a measure-unit conversion factor for
that drug/segment pair; without one the reference cannot be applied and the
record is reported as ``not_converted``. Which reference is read (adult or
pediatric) depends on the segment type.

``calculate_dosemax_uniq`` applies that result to a single ``medatributos``
record, covered here through its repository boundary.

The functions are reached through ``__wrapped__`` to bypass the
``@has_permission`` gate — no request context or database is involved.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from exception.validation_error import ValidationError
from models.enums import SegmentTypeEnum
from models.main import Drug, DrugAttributes, Substance
from models.segment import Segment
from services.admin import admin_drug_service

# The undecorated business logic (skips the permission gate).
_max_dose_ref = admin_drug_service.get_max_dose_ref.__wrapped__
_dosemax_uniq = admin_drug_service.calculate_dosemax_uniq.__wrapped__


def _segment(id=1, type=SegmentTypeEnum.ADULT.value):
    segment = Segment()
    segment.id = id
    segment.description = "Adulto"
    segment.type = type
    return segment


def _drug(id=100):
    drug = Drug()
    drug.id = id
    drug.name = "Dipirona 500mg comprimido"
    drug.sctid = 26472009
    return drug


def _attributes(id_drug=100, id_segment=1, use_weight=False):
    attributes = DrugAttributes()
    attributes.idDrug = id_drug
    attributes.idSegment = id_segment
    attributes.useWeight = use_weight
    return attributes


def _substance(
    *,
    maxdose_adult=None,
    maxdose_adult_weight=None,
    maxdose_pediatric=None,
    maxdose_pediatric_weight=None,
    default_measureunit="mg",
):
    substance = Substance()
    substance.id = 26472009
    substance.name = "dipirona"
    substance.maxdose_adult = maxdose_adult
    substance.maxdose_adult_weight = maxdose_adult_weight
    substance.maxdose_pediatric = maxdose_pediatric
    substance.maxdose_pediatric_weight = maxdose_pediatric_weight
    substance.default_measureunit = default_measureunit
    return substance


def _conversion(*, id_drug=100, id_segment=1, measureunit_nh="mg", factor=1):
    """Build a conversion row as returned by drugs_repository.get_conversions."""
    return SimpleNamespace(
        MeasureUnitConvert=SimpleNamespace(
            idDrug=id_drug, idSegment=id_segment, factor=factor
        ),
        MeasureUnit=SimpleNamespace(measureunit_nh=measureunit_nh),
    )


def _run_max_dose_ref(
    *, substance, segment=None, conversions=None, attributes=None, drug=None
):
    return _max_dose_ref(
        attributes=attributes or _attributes(),
        drug=drug or _drug(),
        segment=segment or _segment(),
        substance=substance,
        conversions=conversions if conversions is not None else [_conversion()],
    )


# ---------------------------------------------------------------------------
# get_max_dose_ref
# ---------------------------------------------------------------------------


def test_segment_without_type_is_rejected():
    """An unconfigured segment type cannot pick between adult and pediatric doses."""
    with pytest.raises(ValidationError) as excinfo:
        _run_max_dose_ref(
            substance=_substance(maxdose_adult=4000),
            segment=_segment(type=None),
        )

    assert excinfo.value.code == "errors.businessRules"


def test_substance_without_reference_dose_reports_no_reference():
    """A substance with no max dose configured yields no reference at all."""
    result = _run_max_dose_ref(substance=_substance())

    assert result["type"] == "no_reference"
    assert "dosemax" not in result
    assert "dosemaxWeight" not in result


def test_result_always_identifies_the_medatributos_record():
    """The drug/segment pair is echoed back so the bulk update can target the row."""
    result = _run_max_dose_ref(
        substance=_substance(),
        attributes=_attributes(id_drug=321, id_segment=7),
        drug=_drug(id=321),
        segment=_segment(id=7),
    )

    assert result["idDrug"] == 321
    assert result["idSegment"] == 7


def test_reference_without_a_conversion_factor_is_not_converted():
    """Without a factor for the drug's unit the reference cannot be applied."""
    result = _run_max_dose_ref(substance=_substance(maxdose_adult=4000), conversions=[])

    assert result["type"] == "not_converted"
    assert "dosemax" not in result


def test_adult_segment_uses_the_adult_reference():
    """An adult segment reads maxdose_adult / maxdose_adult_weight."""
    result = _run_max_dose_ref(
        substance=_substance(
            maxdose_adult=4000,
            maxdose_adult_weight=60,
            maxdose_pediatric=1000,
            maxdose_pediatric_weight=15,
        ),
        segment=_segment(type=SegmentTypeEnum.ADULT.value),
    )

    assert result["type"] == "converted"
    assert result["dosemax"] == 4000
    assert result["dosemaxWeight"] == 60


def test_pediatric_segment_uses_the_pediatric_reference():
    """A pediatric segment reads maxdose_pediatric / maxdose_pediatric_weight."""
    result = _run_max_dose_ref(
        substance=_substance(
            maxdose_adult=4000,
            maxdose_adult_weight=60,
            maxdose_pediatric=1000,
            maxdose_pediatric_weight=15,
        ),
        segment=_segment(type=SegmentTypeEnum.PEDIATRIC.value),
    )

    assert result["type"] == "converted"
    assert result["dosemax"] == 1000
    assert result["dosemaxWeight"] == 15


def test_reference_dose_is_multiplied_by_the_conversion_factor():
    """The reference is expressed in the drug's own measure unit."""
    result = _run_max_dose_ref(
        substance=_substance(maxdose_adult=4000, maxdose_adult_weight=60),
        conversions=[_conversion(factor=0.002)],
    )

    assert result["type"] == "converted"
    assert result["dosemax"] == 8
    assert result["dosemaxWeight"] == 0.12


def test_converted_doses_are_rounded_to_three_decimals():
    """Converted values keep at most three decimals."""
    result = _run_max_dose_ref(
        substance=_substance(maxdose_adult=1, maxdose_adult_weight=2),
        conversions=[_conversion(factor=1 / 3)],
    )

    assert result["dosemax"] == 0.333
    assert result["dosemaxWeight"] == 0.667


def test_only_the_configured_reference_is_converted():
    """A weight-only reference does not produce an absolute max dose, and vice versa."""
    weight_only = _run_max_dose_ref(
        substance=_substance(maxdose_adult_weight=60),
        conversions=[_conversion(factor=2)],
    )
    assert weight_only["type"] == "converted"
    assert weight_only["dosemaxWeight"] == 120
    assert "dosemax" not in weight_only

    absolute_only = _run_max_dose_ref(
        substance=_substance(maxdose_adult=4000),
        conversions=[_conversion(factor=2)],
    )
    assert absolute_only["type"] == "converted"
    assert absolute_only["dosemax"] == 8000
    assert "dosemaxWeight" not in absolute_only


@pytest.mark.parametrize(
    "conversion",
    [
        pytest.param(_conversion(id_drug=999), id="other-drug"),
        pytest.param(_conversion(id_segment=99), id="other-segment"),
        pytest.param(_conversion(measureunit_nh="ml"), id="other-measure-unit"),
    ],
)
def test_conversion_lookup_matches_drug_segment_and_unit(conversion):
    """A factor belonging to another drug, segment or unit is not reused."""
    result = _run_max_dose_ref(
        substance=_substance(maxdose_adult=4000, default_measureunit="mg"),
        conversions=[conversion],
    )

    assert result["type"] == "not_converted"


def test_conversion_lookup_picks_the_matching_row_from_a_list():
    """The right factor is selected among conversions of several drugs."""
    result = _run_max_dose_ref(
        substance=_substance(maxdose_adult=10),
        conversions=[
            _conversion(id_drug=999, factor=100),
            _conversion(measureunit_nh="ml", factor=50),
            _conversion(factor=3),
        ],
    )

    assert result["dosemax"] == 30


# ---------------------------------------------------------------------------
# calculate_dosemax_uniq
# ---------------------------------------------------------------------------


def _attributes_row(attributes, segment):
    """Build a row as returned by drugs_repository.get_drug_attributes."""
    return SimpleNamespace(
        DrugAttributes=attributes,
        Drug=_drug(),
        Substance=_substance(),
        Segment=segment,
    )


def _run_dosemax_uniq(rows, max_dose_ref):
    with (
        patch.object(
            admin_drug_service.drugs_repository,
            "get_drug_attributes",
            return_value=rows,
        ),
        patch.object(
            admin_drug_service.drugs_repository, "get_conversions", return_value=[]
        ),
        patch.object(admin_drug_service, "get_max_dose_ref", return_value=max_dose_ref),
        patch.object(admin_drug_service, "db"),
    ):
        return _dosemax_uniq(id_drug=100, id_segment=1)


def test_dosemax_uniq_returns_none_for_an_unknown_record():
    """A drug without medatributos for the segment has nothing to calculate."""
    assert _run_dosemax_uniq(rows=[], max_dose_ref={"type": "no_reference"}) is None


def test_dosemax_uniq_applies_the_converted_reference():
    """A converted reference is stored and promoted to the effective max dose."""
    attributes = _attributes(use_weight=False)

    result = _run_dosemax_uniq(
        rows=[_attributes_row(attributes, _segment())],
        max_dose_ref={"type": "converted", "dosemax": 8, "dosemaxWeight": 0.12},
    )

    assert result is attributes
    assert attributes.ref_maxdose == 8
    assert attributes.ref_maxdose_weight == 0.12
    assert attributes.maxDose == 8


def test_dosemax_uniq_uses_the_weight_reference_for_weight_based_drugs():
    """Drugs prescribed per kg take the weight reference as effective max dose."""
    attributes = _attributes(use_weight=True)

    _run_dosemax_uniq(
        rows=[_attributes_row(attributes, _segment())],
        max_dose_ref={"type": "converted", "dosemax": 8, "dosemaxWeight": 0.12},
    )

    assert attributes.maxDose == 0.12


def test_dosemax_uniq_clears_the_max_dose_when_the_reference_cannot_be_converted():
    """An unconvertible reference must not leave a stale max dose behind."""
    attributes = _attributes()
    attributes.maxDose = 999

    _run_dosemax_uniq(
        rows=[_attributes_row(attributes, _segment())],
        max_dose_ref={"type": "not_converted"},
    )

    assert attributes.maxDose is None
    assert attributes.ref_maxdose is None
    assert attributes.ref_maxdose_weight is None
