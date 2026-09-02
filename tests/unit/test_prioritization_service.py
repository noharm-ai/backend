import pytest

from services.prioritization_service import _get_first_administration_hour


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
