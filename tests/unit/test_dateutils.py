"""Unit tests for utils.dateutils date helper functions."""

from datetime import date, datetime

import pytest

from utils import dateutils


class TestToIso:
    """Tests for dateutils.to_iso."""

    def test_none_returns_none(self):
        """None input returns None."""
        assert dateutils.to_iso(None) is None

    def test_string_returned_unchanged(self):
        """A string is returned as-is (already assumed ISO)."""
        assert dateutils.to_iso("2024-01-01") == "2024-01-01"

    def test_datetime_converted_to_isoformat(self):
        """A datetime is converted with isoformat()."""
        assert dateutils.to_iso(datetime(2024, 1, 1, 10, 30, 0)) == "2024-01-01T10:30:00"

    def test_date_converted_to_isoformat(self):
        """A date is converted with isoformat()."""
        assert dateutils.to_iso(date(2024, 1, 1)) == "2024-01-01"


class TestParseDateOrToday:
    """Tests for dateutils.parse_date_or_today."""

    def test_valid_date_parsed(self):
        """A valid YYYY-MM-DD string is parsed to a datetime."""
        assert dateutils.parse_date_or_today("2024-03-15") == datetime(2024, 3, 15)

    @pytest.mark.parametrize(
        "bad_text",
        ["not-a-date", "", "2024/03/15", "15-03-2024", "2024-13-40"],
    )
    def test_invalid_date_returns_today(self, bad_text):
        """An unparseable string falls back to today's date."""
        assert dateutils.parse_date_or_today(bad_text) == date.today()


class TestData2Age:
    """Tests for dateutils.data2age."""

    def test_none_returns_empty_string(self):
        """None birthdate returns an empty string."""
        assert dateutils.data2age(None) == ""

    def test_plain_date_string(self):
        """A plain YYYY-MM-DD birthdate yields the age in whole years."""
        birthdate = "1990-06-15"
        expected = int(
            (datetime.today() - datetime(1990, 6, 15)).days / 365.2425
        )
        assert dateutils.data2age(birthdate) == expected

    def test_iso_timestamp_string_is_truncated(self):
        """The time portion after 'T' is ignored when computing the age."""
        with_time = "1990-06-15T08:45:00"
        without_time = "1990-06-15"
        assert dateutils.data2age(with_time) == dateutils.data2age(without_time)

    def test_newborn_is_zero(self):
        """A birthdate of today gives age 0."""
        today_str = date.today().strftime("%Y-%m-%d")
        assert dateutils.data2age(today_str) == 0


class TestDateOverlap:
    """Tests for dateutils.date_overlap."""

    def test_overlapping_ranges(self):
        """Two ranges that share time overlap."""
        assert (
            dateutils.date_overlap(
                datetime(2024, 1, 1),
                datetime(2024, 1, 10),
                datetime(2024, 1, 5),
                datetime(2024, 1, 15),
            )
            is True
        )

    def test_fully_contained_range(self):
        """A range fully inside another overlaps."""
        assert (
            dateutils.date_overlap(
                datetime(2024, 1, 1),
                datetime(2024, 1, 31),
                datetime(2024, 1, 10),
                datetime(2024, 1, 20),
            )
            is True
        )

    def test_disjoint_ranges(self):
        """Ranges that never share time do not overlap."""
        assert (
            dateutils.date_overlap(
                datetime(2024, 1, 1),
                datetime(2024, 1, 10),
                datetime(2024, 2, 1),
                datetime(2024, 2, 10),
            )
            is False
        )

    def test_touching_boundaries_do_not_overlap(self):
        """Ranges that only touch at the boundary are not considered overlapping (strict comparison)."""
        assert (
            dateutils.date_overlap(
                datetime(2024, 1, 1),
                datetime(2024, 1, 10),
                datetime(2024, 1, 10),
                datetime(2024, 1, 20),
            )
            is False
        )
