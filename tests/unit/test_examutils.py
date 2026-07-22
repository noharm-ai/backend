"""Unit tests for utils.examutils renal-function estimators.

These calculators (MDRD, Cockcroft-Gault, CKD-EPI, Schwartz) turn a
creatinine value plus patient demographics into an estimated glomerular
filtration rate. They are pure functions, so we validate them by
re-deriving the expected result from the published formula rather than
hard-coding numbers that depend on the patient's age today.
"""

from datetime import datetime

import pytest

from utils import dateutils, examutils

# A birthdate old enough that data2age never rounds to 0 regardless of the
# current date, keeping the age-dependent formulas stable over time.
ADULT_BIRTHDATE = datetime(1980, 1, 1)


def _adult_age():
    """Age (in whole years) the calculators will compute for ADULT_BIRTHDATE."""
    return dateutils.data2age(ADULT_BIRTHDATE.isoformat())


# --------------------------------------------------------------------------
# Schwartz 2 - age independent, so we can assert exact values.
# --------------------------------------------------------------------------


def test_schwartz2_exact_value():
    """eGFR = 0.413 * height / creatinine, rounded to one decimal."""
    result = examutils.schwartz2_calc(cr=1.0, height=100)
    assert result["value"] == 41.3
    assert result["initials"] == "Schwartz 2"
    assert result["unit"] == "mL/min/1.73m²"


def test_schwartz2_alert_below_reference():
    """Values under the 90 reference raise an alert."""
    assert examutils.schwartz2_calc(cr=1.0, height=100)["alert"] is True


def test_schwartz2_no_alert_above_reference():
    """Values at or above the 90 reference do not alert."""
    # 0.413 * 250 / 1.0 = 103.25 -> above 90
    assert examutils.schwartz2_calc(cr=1.0, height=250)["alert"] is False


@pytest.mark.parametrize(
    "cr, height",
    [("abc", 100), (1.0, None), (None, 100)],
)
def test_schwartz2_invalid_input_returns_empty(cr, height):
    """Non-numeric creatinine or height yields the empty placeholder."""
    result = examutils.schwartz2_calc(cr=cr, height=height)
    assert result["value"] is None
    assert result["initials"] == "Schwartz 2"


def test_schwartz2_zero_creatinine_avoids_division():
    """A creatinine of 0 must not raise; it yields a zeroed estimate."""
    assert examutils.schwartz2_calc(cr=0, height=100)["value"] == 0


# --------------------------------------------------------------------------
# Schwartz 1 - age drives the k constant.
# --------------------------------------------------------------------------


def test_schwartz1_adult_male_uses_k_0_7():
    """Adult male k = 0.7, so eGFR = 0.7 * height / creatinine."""
    result = examutils.schwartz1_calc(cr=1.0, birthdate=ADULT_BIRTHDATE, gender="M", height=100)
    assert result["value"] == 70.0


def test_schwartz1_adult_female_uses_k_0_55():
    """Adult female k = 0.55, so eGFR = 0.55 * height / creatinine."""
    result = examutils.schwartz1_calc(cr=1.0, birthdate=ADULT_BIRTHDATE, gender="F", height=100)
    assert result["value"] == 55.0


@pytest.mark.parametrize(
    "cr, birthdate, height",
    [("abc", ADULT_BIRTHDATE, 100), (1.0, None, 100), (1.0, ADULT_BIRTHDATE, "x")],
)
def test_schwartz1_invalid_input_returns_empty(cr, birthdate, height):
    """Missing/invalid creatinine, birthdate or height yields empty placeholder."""
    result = examutils.schwartz1_calc(cr=cr, birthdate=birthdate, gender="M", height=height)
    assert result["value"] is None


# --------------------------------------------------------------------------
# MDRD - re-derive from the published equation.
# --------------------------------------------------------------------------


def test_mdrd_matches_reference_formula():
    """MDRD value matches an independent re-derivation of the equation."""
    cr = 1.2
    age = _adult_age()
    expected = round(175 * cr ** (-1.154) * age ** (-0.203), 1)

    result = examutils.mdrd_calc(cr=cr, birthdate=ADULT_BIRTHDATE, gender="M", skinColor="B")
    assert result["value"] == expected
    assert result["initials"] == "MDRD"


def test_mdrd_female_factor():
    """Female result equals the male result scaled by the 0.742 factor."""
    male = examutils.mdrd_calc(cr=1.0, birthdate=ADULT_BIRTHDATE, gender="M", skinColor="B")
    female = examutils.mdrd_calc(cr=1.0, birthdate=ADULT_BIRTHDATE, gender="F", skinColor="B")
    assert female["value"] == pytest.approx(male["value"] * 0.742, abs=0.1)


def test_mdrd_alert_below_50():
    """eGFR under 50 raises an alert."""
    # High creatinine drives eGFR down below the 50 threshold.
    result = examutils.mdrd_calc(cr=5.0, birthdate=ADULT_BIRTHDATE, gender="M", skinColor="B")
    assert result["value"] < 50
    assert result["alert"] is True


@pytest.mark.parametrize(
    "cr, birthdate",
    [("abc", ADULT_BIRTHDATE), (1.0, None)],
)
def test_mdrd_invalid_input_returns_empty(cr, birthdate):
    """Invalid creatinine or missing birthdate yields empty placeholder."""
    result = examutils.mdrd_calc(cr=cr, birthdate=birthdate, gender="M", skinColor="B")
    assert result["value"] is None
    assert result["initials"] == "MDRD"


# --------------------------------------------------------------------------
# Cockcroft-Gault - re-derive from the published equation.
# --------------------------------------------------------------------------


def test_cg_matches_reference_formula():
    """Cockcroft-Gault value matches an independent re-derivation."""
    cr, weight = 1.0, 70
    age = _adult_age()
    expected = round(((140 - age) * weight) / (72 * cr), 1)

    result = examutils.cg_calc(cr=cr, birthdate=ADULT_BIRTHDATE, gender="M", weight=weight)
    assert result["value"] == expected
    assert result["initials"] == "CG"


def test_cg_female_factor():
    """Female result equals the male result scaled by the exact 0.85 factor."""
    male = examutils.cg_calc(cr=1.0, birthdate=ADULT_BIRTHDATE, gender="M", weight=70)
    female = examutils.cg_calc(cr=1.0, birthdate=ADULT_BIRTHDATE, gender="F", weight=70)
    assert female["value"] == pytest.approx(male["value"] * 0.85, abs=0.1)


@pytest.mark.parametrize(
    "cr, birthdate, weight",
    [("abc", ADULT_BIRTHDATE, 70), (1.0, None, 70), (1.0, ADULT_BIRTHDATE, "x")],
)
def test_cg_invalid_input_returns_empty(cr, birthdate, weight):
    """Invalid creatinine/weight or missing birthdate yields empty placeholder."""
    result = examutils.cg_calc(cr=cr, birthdate=birthdate, gender="M", weight=weight)
    assert result["value"] is None
    assert result["initials"] == "CG"


# --------------------------------------------------------------------------
# CKD-EPI (2009 and 2021).
# --------------------------------------------------------------------------


def test_ckd_marks_adjusted_when_height_and_weight_given():
    """Providing height and weight switches CKD to the body-surface-adjusted form."""
    adjusted = examutils.ckd_calc(
        cr=1.0, birthdate=ADULT_BIRTHDATE, gender="M", skinColor="B", height=170, weight=70
    )
    assert adjusted["adjust"] is True
    assert adjusted["initials"] == "CKD-A"
    assert adjusted["unit"] == "ml/min"


def test_ckd_not_adjusted_without_body_metrics():
    """Without height/weight the plain (non-adjusted) CKD form is used."""
    plain = examutils.ckd_calc(
        cr=1.0, birthdate=ADULT_BIRTHDATE, gender="M", skinColor="B", height=None, weight=None
    )
    assert plain["adjust"] is False
    assert plain["initials"] == "CKD"
    assert plain["unit"] == "ml/min/1.73"


@pytest.mark.parametrize(
    "cr, birthdate",
    [("abc", ADULT_BIRTHDATE), (1.0, None)],
)
def test_ckd_invalid_input_returns_empty(cr, birthdate):
    """Invalid creatinine or missing birthdate yields empty placeholder."""
    result = examutils.ckd_calc(
        cr=cr, birthdate=birthdate, gender="M", skinColor="B", height=170, weight=70
    )
    assert result["value"] is None
    assert result["initials"] == "CKD"


def test_ckd_calc_21_matches_reference_formula():
    """CKD-EPI 2021 (male) value matches an independent re-derivation."""
    cr = 1.0
    age = _adult_age()
    g, s, e = 0.9, 1, -1.200  # male, cr > g branch (1.0 > 0.9)
    expected = round(142 * (cr / g) ** e * 0.9938 ** age * s, 1)

    result = examutils.ckd_calc_21(cr=cr, birthdate=ADULT_BIRTHDATE, gender="M")
    assert result["value"] == expected
    assert result["initials"] == "CKD 2021"


@pytest.mark.parametrize(
    "cr, birthdate",
    [("abc", ADULT_BIRTHDATE), (1.0, None)],
)
def test_ckd_calc_21_invalid_input_returns_empty(cr, birthdate):
    """Invalid creatinine or missing birthdate yields empty placeholder."""
    result = examutils.ckd_calc_21(cr=cr, birthdate=birthdate, gender="M")
    assert result["value"] is None
