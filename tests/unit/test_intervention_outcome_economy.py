"""Unit tests for intervention_outcome_service._calc_economy.

``_calc_economy`` is the pure money calculation behind an intervention's daily
economy. It multiplies price-per-dose by the daily frequency for the origin
prescription item and, when a substitute (destiny) item exists, subtracts the
substitute's own price × frequency. All values pass through
``numberutils.none2zero`` first, so ``None``/invalid values behave as zero.

The function is otherwise only exercised indirectly through the DB-backed
outcome endpoint; these tests pin its arithmetic and coercion rules directly.
"""

import pytest

from services import intervention_outcome_service


def _item(price_per_dose, frequency_day):
    """Build the minimal origin/destiny structure _calc_economy reads."""
    return {"item": {"pricePerDose": price_per_dose, "frequencyDay": frequency_day}}


class TestCalcEconomyOriginOnly:
    """No substitute: economy is simply pricePerDose * frequencyDay."""

    @pytest.mark.parametrize(
        "price_per_dose, frequency_day, expected",
        [
            ("10", 2, 20.0),
            ("2.5", 4, 10.0),
            (7, 3, 21.0),
            ("0", 5, 0.0),
            ("10", 0, 0.0),
            ("1.5", 1, 1.5),
        ],
    )
    def test_origin_only_multiplies_price_by_frequency(
        self, price_per_dose, frequency_day, expected
    ):
        """With destiny=None the result is the origin's price × daily frequency."""
        result = intervention_outcome_service._calc_economy(
            origin=_item(price_per_dose, frequency_day),
            destiny=None,
        )
        assert result == expected


class TestCalcEconomyWithDestiny:
    """Substitution: origin cost minus destiny cost."""

    def test_positive_economy_when_substitute_is_cheaper(self):
        """Origin 10*3=30 minus destiny 5*2=10 yields a 20 economy."""
        result = intervention_outcome_service._calc_economy(
            origin=_item("10", 3),
            destiny=_item("5", 2),
        )
        assert result == 20.0

    def test_zero_economy_when_costs_match(self):
        """Equal origin and destiny costs produce no economy."""
        result = intervention_outcome_service._calc_economy(
            origin=_item("8", 2),
            destiny=_item("4", 4),
        )
        assert result == 0.0

    def test_negative_economy_when_substitute_is_more_expensive(self):
        """A pricier substitute results in a negative (added-cost) economy."""
        result = intervention_outcome_service._calc_economy(
            origin=_item("5", 2),
            destiny=_item("10", 3),
        )
        assert result == 10.0 - 30.0


class TestCalcEconomyCoercion:
    """None / invalid values are coerced to zero via none2zero."""

    def test_origin_none_returns_zero(self):
        """A missing origin short-circuits to a zero economy."""
        assert intervention_outcome_service._calc_economy(origin=None, destiny=None) == 0

    def test_none_price_in_origin_counts_as_zero(self):
        """A None price makes the origin contribute nothing."""
        result = intervention_outcome_service._calc_economy(
            origin=_item(None, 5),
            destiny=None,
        )
        assert result == 0.0

    def test_none_frequency_in_origin_counts_as_zero(self):
        """A None frequency makes the origin contribute nothing."""
        result = intervention_outcome_service._calc_economy(
            origin=_item("10", None),
            destiny=None,
        )
        assert result == 0.0

    def test_invalid_destiny_values_count_as_zero(self):
        """Non-numeric destiny values collapse to zero, leaving only origin cost."""
        result = intervention_outcome_service._calc_economy(
            origin=_item("10", 2),
            destiny=_item("abc", None),
        )
        assert result == 20.0

    def test_numeric_strings_are_parsed(self):
        """Numeric strings (as emitted by _outcome_calc) are parsed as floats."""
        result = intervention_outcome_service._calc_economy(
            origin=_item("2.5", 4),
            destiny=_item("1.25", 2),
        )
        assert result == 2.5 * 4 - 1.25 * 2
