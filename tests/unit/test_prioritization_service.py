from datetime import datetime

import pytest

from services.prioritization_service import (
    _get_first_administration_hour,
    _get_prescription_dates_summary,
)


class TestGetFirstAdministrationHour:
    """Teste prioritization_service - _get_first_administration_hour.

    Extracts the first administration hour (0-23) from a sorted intervals
    list. It is used to prioritize the pharmacist work queue, so it must be
    strict about what counts as a valid hour and never raise on odd input.
    """

    @pytest.mark.parametrize(
        "intervals",
        [
            None,
            [],
            "",
        ],
    )
    def test_falsy_intervals_return_none(self, intervals):
        """None, empty list and empty string all yield None"""
        assert _get_first_administration_hour(intervals) is None

    @pytest.mark.parametrize(
        "intervals, expected",
        [
            (["8"], 8),
            (["08"], 8),
            (["00"], 0),
            (["23"], 23),
            (["14", "20"], 14),
        ],
    )
    def test_valid_first_hour_is_returned(self, intervals, expected):
        """A valid digit string as the first item is parsed to its hour value"""
        assert _get_first_administration_hour(intervals) == expected

    def test_only_first_interval_is_considered(self):
        """The hour is taken from the first item; later items are ignored"""
        assert _get_first_administration_hour(["06", "12", "18"]) == 6

    @pytest.mark.parametrize(
        "intervals",
        [
            [8],  # not a string
            [None],  # not a string
            ["8.5"],  # not a pure digit string
            [" 8"],  # leading space is not a digit
            ["-1"],  # sign makes isdigit() false
            ["abc"],  # non-numeric
            [""],  # empty first item
        ],
    )
    def test_non_digit_first_interval_returns_none(self, intervals):
        """A first item that is not a plain digit string yields None"""
        assert _get_first_administration_hour(intervals) is None

    @pytest.mark.parametrize(
        "intervals",
        [
            ["24"],
            ["25"],
            ["99"],
        ],
    )
    def test_hour_out_of_range_returns_none(self, intervals):
        """A numeric first item outside the 0-23 range yields None"""
        assert _get_first_administration_hour(intervals) is None


class TestGetPrescriptionDatesSummary:
    """Teste prioritization_service - _get_prescription_dates_summary.

    Agg prescriptions store the dates of their inner (individual)
    prescriptions in features["prescriptionDates"]. The summary exposes the
    most recent one and the next one relative to the current date so the
    work queue can be prioritized by them.
    """

    NOW = datetime(2026, 9, 2, 10, 0, 0)

    @pytest.mark.parametrize("dates", [None, [], ()])
    def test_empty_dates_yield_empty_summary(self, dates):
        """No inner dates means no last/next prescription"""
        summary = _get_prescription_dates_summary(dates, now=self.NOW)
        assert summary == {
            "prescriptionDates": [],
            "lastPrescriptionDate": None,
            "nextPrescriptionDate": None,
        }

    def test_last_and_next_dates(self):
        """Last is the max date; next is the first date at or after now"""
        dates = [
            "2026-09-02T14:00:00",
            "2026-09-01T08:00:00",
            "2026-09-02T18:30:00",
        ]
        summary = _get_prescription_dates_summary(dates, now=self.NOW)
        assert summary["prescriptionDates"] == [
            "2026-09-01T08:00:00",
            "2026-09-02T14:00:00",
            "2026-09-02T18:30:00",
        ]
        assert summary["lastPrescriptionDate"] == "2026-09-02T18:30:00"
        assert summary["nextPrescriptionDate"] == "2026-09-02T14:00:00"

    def test_no_next_when_all_dates_are_past(self):
        """Only past inner prescriptions: last is set, next is None"""
        dates = ["2026-09-01T08:00:00", "2026-09-02T09:59:59"]
        summary = _get_prescription_dates_summary(dates, now=self.NOW)
        assert summary["lastPrescriptionDate"] == "2026-09-02T09:59:59"
        assert summary["nextPrescriptionDate"] is None

    def test_date_equal_to_now_counts_as_next(self):
        """A prescription dated exactly now is still the next one"""
        summary = _get_prescription_dates_summary(["2026-09-02T10:00:00"], now=self.NOW)
        assert summary["nextPrescriptionDate"] == "2026-09-02T10:00:00"

    def test_invalid_and_duplicate_values_are_ignored(self):
        """Non-ISO or non-string values are dropped; duplicates collapse"""
        dates = [
            "2026-09-02T14:00:00",
            "2026-09-02T14:00:00",
            "not-a-date",
            None,
            42,
        ]
        summary = _get_prescription_dates_summary(dates, now=self.NOW)
        assert summary["prescriptionDates"] == ["2026-09-02T14:00:00"]
        assert summary["nextPrescriptionDate"] == "2026-09-02T14:00:00"

    def test_timezone_aware_values_are_compared_as_naive(self):
        """An offset-bearing ISO string never raises against a naive now"""
        summary = _get_prescription_dates_summary(
            ["2026-09-02T14:00:00-03:00"], now=self.NOW
        )
        assert summary["nextPrescriptionDate"] == "2026-09-02T14:00:00"
