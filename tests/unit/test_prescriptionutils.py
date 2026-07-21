"""Unit tests for utils.prescriptionutils prescription helper functions."""

from datetime import datetime, timedelta

import pytest

from utils import prescriptionutils


class TestLenghStay:
    """Tests for prescriptionutils.lenghStay (length of hospital stay in days)."""

    def test_none_admission_returns_empty_string(self):
        """A missing admission date returns an empty string."""
        assert prescriptionutils.lenghStay(None, None) == ""

    def test_open_stay_uses_today(self):
        """Without a discharge date the stay is measured up to today."""
        admission = datetime.today() - timedelta(days=10)
        assert prescriptionutils.lenghStay(admission, None) == 10

    def test_closed_stay(self):
        """With a discharge date the stay is the span between the two dates."""
        admission = datetime(2024, 1, 1)
        discharge = datetime(2024, 1, 6)
        assert prescriptionutils.lenghStay(admission, discharge) == 5

    def test_negative_stay_clamped_to_zero(self):
        """A discharge earlier than admission is clamped to zero."""
        admission = datetime(2024, 1, 10)
        discharge = datetime(2024, 1, 1)
        assert prescriptionutils.lenghStay(admission, discharge) == 0


class TestTimeValue:
    """Tests for prescriptionutils.timeValue (human readable time labels)."""

    def test_single_time(self):
        """A single numeric time is rendered as a full 'Às N Horas' label."""
        assert prescriptionutils.timeValue("8") == "Às 8 Horas"

    def test_multiple_times(self):
        """Multiple space-separated times below the cap are joined with 'h' markers."""
        assert prescriptionutils.timeValue("8 14") == "às 8h, às 14h"

    def test_six_or_more_times_returned_unchanged(self):
        """Six or more times are returned unchanged."""
        value = "8 10 12 14 16 18"
        assert prescriptionutils.timeValue(value) == value

    def test_non_numeric_returned_stripped(self):
        """A non-numeric value is returned trimmed of surrounding whitespace."""
        assert prescriptionutils.timeValue("  SN  ") == "SN"


class TestFreqValue:
    """Tests for prescriptionutils.freqValue (special frequency codes)."""

    @pytest.mark.parametrize(
        "code, label",
        [
            (33, "SN"),
            (44, "ACM"),
            (55, "CONT"),
            (66, "AGORA"),
            (99, "N/D"),
        ],
    )
    def test_special_codes(self, code, label):
        """Known special frequency codes map to their labels."""
        assert prescriptionutils.freqValue(code) == label

    def test_regular_frequency_returned_unchanged(self):
        """An ordinary frequency value is returned unchanged."""
        assert prescriptionutils.freqValue(8) == 8


class TestInteractionsList:
    """Tests for prescriptionutils.interactionsList."""

    def test_splits_name_and_id(self):
        """Each entry is split into its name and drug id components."""
        result = prescriptionutils.interactionsList(
            ["Aspirina|123", "Dipirona|456"], "|"
        )
        assert result == [
            {"name": "Aspirina", "idDrug": "123"},
            {"name": "Dipirona", "idDrug": "456"},
        ]

    def test_empty_list(self):
        """An empty input list yields an empty result."""
        assert prescriptionutils.interactionsList([], "|") == []


class TestGetNumericDrugAttributesList:
    """Tests for prescriptionutils.get_numeric_drug_attributes_list."""

    def test_contains_expected_attributes(self):
        """The list exposes the known numeric drug attribute keys."""
        attributes = prescriptionutils.get_numeric_drug_attributes_list()
        assert "antimicro" in attributes
        assert "controlled" in attributes
        assert "chemo" in attributes

    def test_returns_unique_values(self):
        """The attribute list has no duplicates."""
        attributes = prescriptionutils.get_numeric_drug_attributes_list()
        assert len(attributes) == len(set(attributes))


class TestSplitInterval:
    """Tests for prescriptionutils.split_interval."""

    def test_none_returns_empty_list(self):
        """None input returns an empty list."""
        assert prescriptionutils.split_interval(None) == []

    def test_empty_string_returns_empty_list(self):
        """An empty string returns an empty list."""
        assert prescriptionutils.split_interval("") == []

    def test_times_with_minutes_keep_hour_only(self):
        """Tokens with a ':' keep only the hour part."""
        assert prescriptionutils.split_interval("06:00 12:00 18:30") == [
            "06",
            "12",
            "18",
        ]

    def test_plain_hours_preserved(self):
        """Plain hour tokens are preserved."""
        assert prescriptionutils.split_interval("8 12 18") == ["8", "12", "18"]

    def test_extra_spaces_ignored(self):
        """Empty tokens produced by extra spaces are ignored."""
        assert prescriptionutils.split_interval("06:00  12:00") == ["06", "12"]


class TestGenAggId:
    """Tests for prescriptionutils.gen_agg_id (aggregated prescription id)."""

    @pytest.mark.parametrize(
        "admission_number, id_segment, pdate",
        [
            (None, 1, datetime(2024, 3, 15)),
            (42, None, datetime(2024, 3, 15)),
            (42, 1, None),
        ],
    )
    def test_missing_argument_returns_none(self, admission_number, id_segment, pdate):
        """Any missing argument produces a None id."""
        assert prescriptionutils.gen_agg_id(admission_number, id_segment, pdate) is None

    def test_encodes_date_segment_and_admission(self):
        """The id packs year, month, day, segment and admission number."""
        result = prescriptionutils.gen_agg_id(42, 1, datetime(2024, 3, 15))
        assert result == 2403151000000042

    def test_different_days_produce_different_ids(self):
        """Distinct prescription dates produce distinct ids."""
        day1 = prescriptionutils.gen_agg_id(42, 1, datetime(2024, 3, 15))
        day2 = prescriptionutils.gen_agg_id(42, 1, datetime(2024, 3, 16))
        assert day1 != day2


class TestGetPrescriptionItemPeriod:
    """Tests for prescriptionutils.get_prescription_item_period."""

    def test_cpoe_with_previous_period(self):
        """CPOE items with a previous period sum the cpoe and item periods."""
        period, total = prescriptionutils.get_prescription_item_period(
            is_cpoe=True, item_period=2, cpoe_period=3
        )
        assert period == "D3"
        assert total == 5.0

    def test_cpoe_without_previous_period(self):
        """CPOE items without a previous period add one to the cpoe period."""
        period, total = prescriptionutils.get_prescription_item_period(
            is_cpoe=True, item_period=None, cpoe_period=3
        )
        assert period == "D3"
        assert total == 4.0

    def test_cpoe_without_cpoe_period(self):
        """CPOE items without a cpoe period yield an empty label and total of 1."""
        period, total = prescriptionutils.get_prescription_item_period(
            is_cpoe=True, item_period=0, cpoe_period=None
        )
        assert period == ""
        assert total == 1

    def test_non_cpoe_total_period(self):
        """Non-CPOE items report the item period as the total."""
        _, total = prescriptionutils.get_prescription_item_period(
            is_cpoe=False, item_period=5, cpoe_period=None
        )
        assert total == 5.0
