import pytest

from utils import numberutils


class TestIsFloat:
    """Teste numberutils - is_float (safe check whether a value is convertible to float)"""

    @pytest.mark.parametrize(
        "value",
        [
            1,
            0,
            -3,
            1.5,
            -2.75,
            "0",
            "10",
            "3.14",
            "-4.2",
            "  7.5  ",
            "1e3",
            True,
        ],
    )
    def test_convertible_values_return_true(self, value):
        """Numbers and numeric strings are recognized as float-convertible"""
        assert numberutils.is_float(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "abc",
            "1.2.3",
            "10,5",
            [],
            {},
            "  ",
        ],
    )
    def test_non_convertible_values_return_false(self, value):
        """None, empty strings, non-numeric text and containers are rejected"""
        assert numberutils.is_float(value) is False


class TestNone2Zero:
    """Teste numberutils - none2zero (coerce a value to float, defaulting to 0)"""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2.5", 2.5),
            ("10", 10.0),
            (3, 3.0),
            (-4.2, -4.2),
            (0, 0.0),
            ("  1.5 ", 1.5),
        ],
    )
    def test_numeric_values_are_converted_to_float(self, value, expected):
        """Numeric values and numeric strings are converted to their float value"""
        assert numberutils.none2zero(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "abc",
            "1.2.3",
            [],
        ],
    )
    def test_non_numeric_values_default_to_zero(self, value):
        """Non-convertible values (used in economy calculations) default to 0"""
        assert numberutils.none2zero(value) == 0

    def test_result_is_always_float_for_valid_input(self):
        """A convertible value is returned as a float, not the original type"""
        result = numberutils.none2zero(5)
        assert isinstance(result, float)
        assert result == 5.0
