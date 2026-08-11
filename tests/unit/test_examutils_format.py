"""Unit tests for utils.examutils.formatExam and _skinChar.

``formatExam`` is the pure helper that turns a raw lab-exam value into the
dict the frontend renders: it coerces the value to a number, decides whether
it falls outside the segment's reference range (``alert``) and computes the
percentage variation against the previous value (``delta``). ``_skinChar``
normalises a skin-colour string to the single upper-case initial used by the
renal-function estimators.

These are pure functions, so we validate them by re-deriving the expected
result from the formula rather than hitting the database.
"""

import pytest

from utils import examutils


class _Ref:
    """Minimal stand-in for a segment exam reference row.

    ``formatExam`` only reads ``min``/``max``/``ref``/``initials``/``name``/
    ``tp_exam_ref`` off the reference object, so a plain attribute holder is
    enough to drive it.
    """

    def __init__(self, min_val, max_val, ref="ref-text", initials="INI",
                 name="Exam Name", tp_exam_ref=7):
        self.min = min_val
        self.max = max_val
        self.ref = ref
        self.initials = initials
        self.name = name
        self.tp_exam_ref = tp_exam_ref


class TestFormatExamAlert:
    """formatExam - out-of-range detection against the segment reference."""

    def test_value_inside_range_does_not_alert(self):
        """A value within [min, max] is not flagged."""
        seg = {"tgo": _Ref(min_val=5, max_val=40)}
        result = examutils.formatExam(
            value=20, typeExam="tgo", unit="U/L", date=None, segExam=seg
        )
        assert result["alert"] is False
        assert result["value"] == 20
        assert result["unit"] == "U/L"

    def test_value_on_boundary_does_not_alert(self):
        """The range is inclusive on both ends."""
        seg = {"tgo": _Ref(min_val=5, max_val=40)}
        low = examutils.formatExam(
            value=5, typeExam="tgo", unit="U/L", date=None, segExam=seg
        )
        high = examutils.formatExam(
            value=40, typeExam="tgo", unit="U/L", date=None, segExam=seg
        )
        assert low["alert"] is False
        assert high["alert"] is False

    @pytest.mark.parametrize("value", [4.9, 41, 100])
    def test_value_outside_range_alerts(self, value):
        """A value below min or above max raises an alert."""
        seg = {"tgo": _Ref(min_val=5, max_val=40)}
        result = examutils.formatExam(
            value=value, typeExam="tgo", unit="U/L", date=None, segExam=seg
        )
        assert result["alert"] is True

    def test_reference_metadata_is_passed_through(self):
        """When a reference exists its metadata is echoed into the payload."""
        ref = _Ref(min_val=5, max_val=40, ref="5 a 40", initials="TGO",
                   name="Transaminase", tp_exam_ref=3)
        result = examutils.formatExam(
            value=10, typeExam="tgo", unit="U/L", date=None, segExam={"tgo": ref}
        )
        assert result["ref"] == "5 a 40"
        assert result["initials"] == "TGO"
        assert result["min"] == 5
        assert result["max"] == 40
        assert result["name"] == "Transaminase"
        assert result["tp_exam_ref"] == 3
        assert result["manual"] is False


class TestFormatExamUnknownType:
    """formatExam - behaviour when the exam type has no reference."""

    def test_unknown_type_never_alerts(self):
        """Without a reference range there is nothing to compare against."""
        result = examutils.formatExam(
            value=999, typeExam="unknown", unit="mg", date=None, segExam={}
        )
        assert result["alert"] is False

    def test_unknown_type_uses_type_as_name_and_initials(self):
        """The exam type becomes both the display name and the initials."""
        result = examutils.formatExam(
            value=1, typeExam="unknown", unit="mg", date=None, segExam={}
        )
        assert result["name"] == "unknown"
        assert result["initials"] == "unknown"
        assert result["min"] == ""
        assert result["max"] == ""
        assert result["tp_exam_ref"] is None


class TestFormatExamValueCoercion:
    """formatExam - value coercion via numberutils.none2zero."""

    def test_numeric_string_is_coerced_to_float(self):
        """A numeric string is stored as its float value."""
        seg = {"tgo": _Ref(min_val=0, max_val=100)}
        result = examutils.formatExam(
            value="12.5", typeExam="tgo", unit="U/L", date=None, segExam=seg
        )
        assert result["value"] == 12.5

    def test_non_numeric_value_becomes_zero(self):
        """A non-numeric value defaults to 0 (and 0 is below min -> alert)."""
        seg = {"tgo": _Ref(min_val=5, max_val=40)}
        result = examutils.formatExam(
            value="abc", typeExam="tgo", unit="U/L", date=None, segExam=seg
        )
        assert result["value"] == 0
        assert result["alert"] is True

    def test_none_unit_is_rendered_as_empty_string(self):
        """A missing unit is normalised to an empty string, never None."""
        seg = {"tgo": _Ref(min_val=0, max_val=100)}
        result = examutils.formatExam(
            value=10, typeExam="tgo", unit=None, date=None, segExam=seg
        )
        assert result["unit"] == ""


class TestFormatExamDelta:
    """formatExam - percentage variation against the previous value."""

    def test_no_previous_value_yields_none_delta(self):
        """With no prior measurement there is no variation to report."""
        seg = {"tgo": _Ref(min_val=0, max_val=100)}
        result = examutils.formatExam(
            value=10, typeExam="tgo", unit="U/L", date=None, segExam=seg
        )
        assert result["delta"] is None
        assert result["prev"] == 0

    def test_increase_produces_positive_delta(self):
        """A rise from 10 to 12 is a +20% variation."""
        seg = {"tgo": _Ref(min_val=0, max_val=100)}
        result = examutils.formatExam(
            value=12, typeExam="tgo", unit="U/L", date=None, segExam=seg,
            prevValue=10,
        )
        assert result["delta"] == 20.0
        assert result["prev"] == 10

    def test_decrease_produces_negative_delta(self):
        """A drop from 10 to 8 is a -20% variation."""
        seg = {"tgo": _Ref(min_val=0, max_val=100)}
        result = examutils.formatExam(
            value=8, typeExam="tgo", unit="U/L", date=None, segExam=seg,
            prevValue=10,
        )
        assert result["delta"] == -20.0

    def test_zero_previous_value_yields_none_delta(self):
        """A previous value of 0 cannot be a denominator, so delta is None."""
        seg = {"tgo": _Ref(min_val=0, max_val=100)}
        result = examutils.formatExam(
            value=10, typeExam="tgo", unit="U/L", date=None, segExam=seg,
            prevValue=0,
        )
        assert result["delta"] is None


class TestSkinChar:
    """_skinChar - normalise a skin-colour string to its upper-case initial."""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("negra", "N"),
            ("Parda", "P"),
            ("branca", "B"),
            ("amarela", "A"),
            (5, "5"),
        ],
    )
    def test_returns_first_upper_char(self, value, expected):
        """The first character of the stringified value, upper-cased."""
        assert examutils._skinChar(value) == expected

    def test_none_returns_space(self):
        """A missing skin colour maps to a space sentinel, not an error."""
        assert examutils._skinChar(None) == " "
