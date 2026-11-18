"""Tests for DrugList.get_auc_value"""

import math
from unittest.mock import MagicMock

import pytest

from models.enums import DefaultMeasureUnitEnum
from utils.drug_list import CARBOPLATIN_SCTID, DrugList


def make_drug_list(exams=None):
    """Create a DrugList instance with no processed drugs."""
    return DrugList(
        drugList=[],
        interventions=[],
        relations={"stats": {}, "alerts": {}},
        exams=exams,
        agg=False,
        dialysis=None,
        alerts={"stats": {}, "alerts": {}},
        admission_number=1,
    )


def make_pd(
    dose=1000.0,
    doseconv=None,
    sctid=CARBOPLATIN_SCTID,
    measureunit_nh=DefaultMeasureUnitEnum.MG.value,
    default_measure_unit_nh=DefaultMeasureUnitEnum.MG.value,
    use_weight=False,
    convert_factor=None,
    division=None,
    drug=None,  # pass sentinel to override pd[1]; None means "use default mock"
    measure_unit=None,  # pass sentinel to override pd[2]; None means "use default mock"
):
    """Create a mock prescription drug row with the fields used by get_auc_value.

    MagicMock item-assignment (pd[n] = x) does not affect subsequent reads via
    pd[n], so we control __getitem__ directly with a side_effect dict.
    """
    pd0 = MagicMock()
    pd0.dose = dose
    pd0.doseconv = doseconv

    pd1 = None if drug is _NONE_SENTINEL else MagicMock(sctid=sctid)

    pd2 = (
        None
        if measure_unit is _NONE_SENTINEL
        else MagicMock(measureunit_nh=measureunit_nh)
    )

    pd6 = MagicMock()
    pd6.useWeight = use_weight
    pd6.division = division
    pd6.idMeasureUnit = "mg"
    pd0.idMeasureUnit = "mg" if measureunit_nh == pd6.idMeasureUnit else "other"

    items = {0: pd0, 1: pd1, 2: pd2, 6: pd6}

    pd = MagicMock()
    pd.__getitem__ = MagicMock(side_effect=lambda k: items[k])
    pd.default_measure_unit_nh = default_measure_unit_nh
    pd.measure_unit_convert_factor = convert_factor
    pd.MeasureUnit = pd2
    return pd


# Sentinel used so callers can explicitly request None for a slot.
_NONE_SENTINEL = object()


# ---------------------------------------------------------------------------
# Early-return guards — return None when the drug is not relevant
# ---------------------------------------------------------------------------


def test_returns_none_when_drug_is_none():
    """Should return None when drug (pd[1]) is None."""
    dl = make_drug_list(exams={"cg": {"value": 60}, "ckd21": {"value": 60}})
    pd = make_pd(drug=_NONE_SENTINEL)
    assert dl.get_auc_value(pd) is None


def test_returns_none_when_wrong_sctid():
    """Should return None when drug sctid is not Carboplatin's (386905002)."""
    dl = make_drug_list(exams={"cg": {"value": 60}, "ckd21": {"value": 60}})
    pd = make_pd(sctid=12345)
    assert dl.get_auc_value(pd) is None


# ---------------------------------------------------------------------------
# Missing-info guards — Carboplatin identified but data is incomplete
# Returns a dict with auc_cg/auc_ckd = None and missing_cg/missing_ckd set
# ---------------------------------------------------------------------------


def test_returns_missing_when_measure_unit_is_none():
    """Should return missing info when measure unit (pd[2]) is None."""
    dl = make_drug_list(exams={"cg": {"value": 60}, "ckd21": {"value": 60}})
    pd = make_pd(measure_unit=_NONE_SENTINEL)
    result = dl.get_auc_value(pd)
    assert result["auc_cg"] is None
    assert result["auc_ckd"] is None
    assert result["missing_cg"] == "measure_unit"
    assert result["missing_ckd"] == "measure_unit"


def test_returns_missing_when_exams_is_none():
    """Should return missing info when exams is None."""
    dl = make_drug_list(exams=None)
    pd = make_pd()
    result = dl.get_auc_value(pd)
    assert result["auc_cg"] is None
    assert result["auc_ckd"] is None
    assert result["missing_cg"] == "exams"
    assert result["missing_ckd"] == "exams"


def test_returns_missing_when_dose_is_zero():
    """Should return missing info when dose resolves to zero/falsy."""
    dl = make_drug_list(exams={"cg": {"value": 75}, "ckd21": {"value": 60}})
    pd = make_pd(dose=0)
    result = dl.get_auc_value(pd)
    assert result["auc_cg"] is None
    assert result["auc_ckd"] is None
    assert result["missing_cg"] == "dose"
    assert result["missing_ckd"] == "dose"


def test_returns_missing_when_dose_is_none():
    """Should return missing info when dose is None."""
    dl = make_drug_list(exams={"cg": {"value": 75}, "ckd21": {"value": 60}})
    pd = make_pd(dose=None)
    result = dl.get_auc_value(pd)
    assert result["auc_cg"] is None
    assert result["auc_ckd"] is None
    assert result["missing_cg"] == "dose"
    assert result["missing_ckd"] == "dose"


def test_returns_missing_when_neither_exam_is_present():
    """Should return missing info for both formulas when neither 'cg' nor 'ckd21' is in exams."""
    dl = make_drug_list(exams={"weight": 70, "height": 170})
    pd = make_pd(dose=1000.0)
    result = dl.get_auc_value(pd)
    assert result["auc_cg"] is None
    assert result["auc_ckd"] is None
    assert result["missing_cg"] == "no_cg_exam"
    assert result["missing_ckd"] == "no_ckd21_exam"


# ---------------------------------------------------------------------------
# Dose resolution
# ---------------------------------------------------------------------------


def test_uses_dose_when_measure_unit_is_mg():
    """Should use prescription_drug.dose when measure unit is already MG."""
    dl = make_drug_list(
        exams={"cg": {"value": 75}, "ckd21": {"value": 60}, "weight": 70, "height": 170}
    )
    pd = make_pd(dose=1000.0, doseconv=9999.0, measureunit_nh=DefaultMeasureUnitEnum.MG.value)
    result = dl.get_auc_value(pd)
    # CG branch uses dose=1000, not doseconv
    assert result["auc_cg"] == round(1000.0 / (75 + 25), 2)


def test_converts_dose_when_default_unit_is_mg_and_prescribed_unit_differs():
    """Prescribed in another unit, the dose is converted live with the current
    factor; the stored doseconv (the outlier score key) is not read."""
    dl = make_drug_list(
        exams={"cg": {"value": 75}, "ckd21": {"value": 60}, "weight": 70, "height": 170}
    )
    pd = make_pd(
        dose=50.0,
        doseconv=800.0,
        measureunit_nh=DefaultMeasureUnitEnum.ML.value,
        default_measure_unit_nh=DefaultMeasureUnitEnum.MG.value,
        convert_factor=10,
    )
    result = dl.get_auc_value(pd)
    # 50 ml * 10 = 500 mg: auc_cg = round(500 / (75 + 25), 2) = 5.0
    assert result["auc_cg"] == round(500.0 / (75 + 25), 2)


def test_converted_dose_ignores_range_rounded_doseconv():
    """A drug with dose ranges has a doseconv rounded to the range: the AUC
    uses the dose times the factor."""
    dl = make_drug_list(exams={"cg": {"value": 75}})
    pd = make_pd(
        dose=45.0,
        doseconv=500.0,
        measureunit_nh=DefaultMeasureUnitEnum.ML.value,
        default_measure_unit_nh=DefaultMeasureUnitEnum.MG.value,
        convert_factor=10,
        division=100,
    )
    result = dl.get_auc_value(pd)
    assert result["auc_cg"] == round(450.0 / (75 + 25), 2)


def test_returns_missing_dose_without_convert_factor():
    """Prescribed in another unit with no factor, the dose in mg can't be
    told: no AUC (doseconv would be the dose in the prescribed unit)."""
    dl = make_drug_list(exams={"cg": {"value": 75}})
    pd = make_pd(
        dose=50.0,
        doseconv=50.0,
        measureunit_nh=DefaultMeasureUnitEnum.ML.value,
        default_measure_unit_nh=DefaultMeasureUnitEnum.MG.value,
        convert_factor=None,
    )
    result = dl.get_auc_value(pd)
    assert result["auc_cg"] is None
    assert result["missing_cg"] == "dose"
    assert result["missing_ckd"] == "dose"


def test_uses_doseconv_for_dose_diferenciada():
    """Without a dose (dose diferenciada) doseconv is the daily total in the
    default unit and is used."""
    dl = make_drug_list(exams={"cg": {"value": 75}})
    pd = make_pd(
        dose=None,
        doseconv=800.0,
        measureunit_nh=DefaultMeasureUnitEnum.ML.value,
        default_measure_unit_nh=DefaultMeasureUnitEnum.MG.value,
    )
    result = dl.get_auc_value(pd)
    assert result["auc_cg"] == round(800.0 / (75 + 25), 2)


def test_returns_missing_when_use_weight_requires_unimplemented_conversion():
    """Should return missing info when useWeight=True triggers the unimplemented conversion path."""
    dl = make_drug_list(
        exams={"cg": {"value": 75}, "ckd21": {"value": 60}, "weight": 70, "height": 170}
    )
    pd = make_pd(
        measureunit_nh=DefaultMeasureUnitEnum.ML.value,
        default_measure_unit_nh=DefaultMeasureUnitEnum.MG.value,
        use_weight=True,
    )
    result = dl.get_auc_value(pd)
    assert result["auc_cg"] is None
    assert result["auc_ckd"] is None
    assert result["missing_cg"] == "weight_conversion"
    assert result["missing_ckd"] == "weight_conversion"


# ---------------------------------------------------------------------------
# CG formula: auc_cg = round(dose / (cg + 25), 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dose, cg_value",
    [
        (1000.0, 75),
        (500.0, 50),
        (1500.0, 100),
        (250.0, 25),
    ],
)
def test_cg_formula(dose, cg_value):
    """auc_cg = round(dose / (cg + 25), 2)"""
    dl = make_drug_list(
        exams={
            "cg": {"value": cg_value},
            "ckd21": {"value": 60},
            "weight": 70,
            "height": 170,
        }
    )
    pd = make_pd(dose=dose)
    result = dl.get_auc_value(pd)
    assert result["auc_cg"] == round(dose / (cg_value + 25), 2)


def test_cg_only_returns_auc_cg_and_missing_ckd():
    """When only 'cg' is in exams, auc_cg is calculated and missing_ckd is set."""
    dl = make_drug_list(exams={"cg": {"value": 75}})
    pd = make_pd(dose=1000.0)
    result = dl.get_auc_value(pd)
    assert result["auc_cg"] == round(1000.0 / (75 + 25), 2)
    assert result["auc_ckd"] is None
    assert result["missing_cg"] is None
    assert result["missing_ckd"] == "no_ckd21_exam"


# ---------------------------------------------------------------------------
# CKD21 formula: auc_ckd = round(dose / (ckd21 * body_surface / 1.73 + 25), 2)
# body_surface = sqrt((weight * height) / 3600)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dose, ckd21_value, weight, height",
    [
        (1000.0, 60, 70, 170),
        (500.0, 45, 60, 160),
        (1500.0, 80, 90, 180),
    ],
)
def test_ckd21_formula(dose, ckd21_value, weight, height):
    """auc_ckd = round(dose / (ckd21 * body_surface / 1.73 + 25), 2)"""
    dl = make_drug_list(
        exams={"ckd21": {"value": ckd21_value}, "weight": weight, "height": height}
    )
    pd = make_pd(dose=dose)
    result = dl.get_auc_value(pd)

    body_surface = math.sqrt((weight * height) / 3600)
    expected_ckd = round(dose / (ckd21_value * body_surface / 1.73 + 25), 2)

    assert result["auc_ckd"] == expected_ckd
    assert result["auc_cg"] is None
    assert result["missing_cg"] == "no_cg_exam"
    assert result["missing_ckd"] is None


def test_ckd21_skipped_when_weight_is_missing():
    """Should set missing_ckd='weight_height' when ckd21 is present but weight is absent."""
    dl = make_drug_list(exams={"ckd21": {"value": 60}, "height": 170})
    pd = make_pd(dose=1000.0)
    result = dl.get_auc_value(pd)
    assert result["auc_ckd"] is None
    assert result["missing_ckd"] == "weight_height"
    assert result["auc_cg"] is None
    assert result["missing_cg"] == "no_cg_exam"


def test_ckd21_skipped_when_height_is_missing():
    """Should set missing_ckd='weight_height' when ckd21 is present but height is absent."""
    dl = make_drug_list(exams={"ckd21": {"value": 60}, "weight": 70})
    pd = make_pd(dose=1000.0)
    result = dl.get_auc_value(pd)
    assert result["auc_ckd"] is None
    assert result["missing_ckd"] == "weight_height"
    assert result["auc_cg"] is None
    assert result["missing_cg"] == "no_cg_exam"


def test_ckd21_skipped_when_weight_is_zero():
    """Should set missing_ckd='weight_height' when weight is 0 (body surface cannot be calculated)."""
    dl = make_drug_list(exams={"ckd21": {"value": 60}, "weight": 0, "height": 170})
    pd = make_pd(dose=1000.0)
    result = dl.get_auc_value(pd)
    assert result["auc_ckd"] is None
    assert result["missing_ckd"] == "weight_height"
    assert result["auc_cg"] is None
    assert result["missing_cg"] == "no_cg_exam"


# ---------------------------------------------------------------------------
# Both CG and CKD21 present
# ---------------------------------------------------------------------------


def test_both_cg_and_ckd21_returns_both_values():
    """Should return both auc_cg and auc_ckd when both exams and body measurements are present."""
    weight, height = 70, 170
    cg_value, ckd21_value, dose = 75, 60, 1000.0

    dl = make_drug_list(
        exams={
            "cg": {"value": cg_value},
            "ckd21": {"value": ckd21_value},
            "weight": weight,
            "height": height,
        }
    )
    pd = make_pd(dose=dose)
    result = dl.get_auc_value(pd)

    body_surface = math.sqrt((weight * height) / 3600)
    expected_cg = round(dose / (cg_value + 25), 2)
    expected_ckd = round(dose / (ckd21_value * body_surface / 1.73 + 25), 2)

    assert result["auc_cg"] == expected_cg
    assert result["auc_ckd"] == expected_ckd
    assert result["missing_cg"] is None
    assert result["missing_ckd"] is None


def test_both_present_but_ckd21_without_body_measurements_returns_only_cg():
    """When ckd21 is present but weight/height are missing, only auc_cg should be set."""
    dl = make_drug_list(exams={"cg": {"value": 75}, "ckd21": {"value": 60}})
    pd = make_pd(dose=1000.0)
    result = dl.get_auc_value(pd)

    assert result["auc_cg"] == round(1000.0 / (75 + 25), 2)
    assert result["auc_ckd"] is None
    assert result["missing_cg"] is None
    assert result["missing_ckd"] == "weight_height"
