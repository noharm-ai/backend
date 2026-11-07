"""Unit tests: which prescribed items are compared for interactions.

Two items of a prescription are only checked against each other when their
periods match (``alert_interaction_service._periods_compared``):

* outside CPOE, when both expire on the same day;
* in CPOE, when their periods (prescription day to expiry day) overlap.

Only the day counts, never the time. When the rule leaves a pair out, the
interaction trace explains it to the maintainer with the sentence built by
``get_period_mismatch``; when the pair is compared, there is nothing to
explain and it returns ``None``. These tests pin down both the rule and the
sentences.
"""

from datetime import datetime

import pytest

from services.alert_interaction_service import get_period_mismatch


def _item(name: str, start: str, end: str) -> dict:
    """A relation item as build_relation_item makes it (only what is compared)"""
    return {
        "drug": name,
        "prescriptionDate": datetime.fromisoformat(start).isoformat(),
        "expireDate": datetime.fromisoformat(end).isoformat(),
    }


class TestNotCpoe:
    """Outside CPOE: only items expiring the same day are compared"""

    def test_same_expire_day_is_compared(self):
        """Same expiry day, different start: compared"""
        drug_a = _item("DROGA A", "2024-01-01 08:00", "2024-01-03 08:00")
        drug_b = _item("DROGA B", "2024-01-02 10:00", "2024-01-03 08:00")

        assert get_period_mismatch(drug_a, drug_b, is_cpoe=False) is None

    def test_time_of_day_is_ignored(self):
        """Expiring at different times of the same day still counts as the same"""
        drug_a = _item("DROGA A", "2024-01-01 08:00", "2024-01-03 00:00")
        drug_b = _item("DROGA B", "2024-01-01 08:00", "2024-01-03 23:59")

        assert get_period_mismatch(drug_a, drug_b, is_cpoe=False) is None

    def test_different_expire_day_is_explained(self):
        """Different expiry days: the reason names both items and their days"""
        drug_a = _item("DROGA A", "2024-01-01 08:00", "2024-01-02 08:00")
        drug_b = _item("DROGA B", "2024-01-01 08:00", "2024-01-03 08:00")

        assert get_period_mismatch(drug_a, drug_b, is_cpoe=False) == (
            "Os itens têm datas de vigência diferentes "
            "(DROGA A: 02/01/2024; DROGA B: 03/01/2024). "
            "Só são comparados itens com a mesma data de vigência."
        )

    def test_overlapping_periods_are_not_enough(self):
        """Overlap alone does not make a non CPOE pair comparable"""
        drug_a = _item("DROGA A", "2024-01-01 08:00", "2024-01-05 08:00")
        drug_b = _item("DROGA B", "2024-01-02 08:00", "2024-01-04 08:00")

        assert get_period_mismatch(drug_a, drug_b, is_cpoe=False) is not None


class TestCpoe:
    """CPOE: items whose periods overlap are compared"""

    @pytest.mark.parametrize(
        "start_b,end_b",
        [
            # b inside a
            ("2024-01-02 08:00", "2024-01-03 08:00"),
            # b starts before a and ends inside it
            ("2023-12-30 08:00", "2024-01-02 08:00"),
            # b starts the day a ends (boundary days count)
            ("2024-01-05 20:00", "2024-01-07 08:00"),
            # b ends the day a starts
            ("2023-12-28 08:00", "2024-01-01 06:00"),
        ],
    )
    def test_overlapping_periods_are_compared(self, start_b, end_b):
        """Any overlap, including a shared boundary day, is compared"""
        drug_a = _item("DROGA A", "2024-01-01 08:00", "2024-01-05 08:00")
        drug_b = _item("DROGA B", start_b, end_b)

        assert get_period_mismatch(drug_a, drug_b, is_cpoe=True) is None
        assert get_period_mismatch(drug_b, drug_a, is_cpoe=True) is None

    def test_different_expire_day_is_compared_when_overlapping(self):
        """Unlike the non CPOE rule, different expiry days may be compared"""
        drug_a = _item("DROGA A", "2024-01-01 08:00", "2024-01-02 08:00")
        drug_b = _item("DROGA B", "2024-01-01 08:00", "2024-01-03 08:00")

        assert get_period_mismatch(drug_a, drug_b, is_cpoe=True) is None

    def test_disjoint_periods_are_explained(self):
        """Periods that don't overlap: the reason gives both periods"""
        drug_a = _item("DROGA A", "2024-01-01 08:00", "2024-01-02 08:00")
        drug_b = _item("DROGA B", "2024-01-04 08:00", "2024-01-06 08:00")

        assert get_period_mismatch(drug_a, drug_b, is_cpoe=True) == (
            "Os períodos de vigência não se sobrepõem "
            "(DROGA A: 01/01/2024 a 02/01/2024; "
            "DROGA B: 04/01/2024 a 06/01/2024). "
            "Em CPOE, só são comparados itens com vigências sobrepostas."
        )

    def test_disjoint_periods_follow_the_argument_order(self):
        """The sentence names the items in the order they were given"""
        drug_a = _item("DROGA A", "2024-01-01 08:00", "2024-01-02 08:00")
        drug_b = _item("DROGA B", "2024-01-04 08:00", "2024-01-06 08:00")

        message = get_period_mismatch(drug_b, drug_a, is_cpoe=True)

        assert message.index("DROGA B") < message.index("DROGA A")

    def test_one_day_gap_is_not_compared(self):
        """A single day between the periods is enough to leave them apart"""
        drug_a = _item("DROGA A", "2024-01-01 08:00", "2024-01-02 23:00")
        drug_b = _item("DROGA B", "2024-01-03 01:00", "2024-01-04 08:00")

        assert get_period_mismatch(drug_a, drug_b, is_cpoe=True) is not None
