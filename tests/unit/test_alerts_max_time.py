"""Unit tests for the maximum treatment time alert (DrugAlertTypeEnum.MAX_TIME).

`alert_service._alert_max_time` warns the pharmacist when a drug has been
prescribed for longer than the maximum treatment period configured on the
drug attributes (`medatributos.tempo_max`). The period that is compared
against that limit is not the raw item period: in CPOE schemas it is the
accumulated period returned by
`prescriptionutils.get_prescription_item_period`, which adds the item period
of the current prescription to the period already carried by the CPOE chain.

The tests below cover the helper directly (pure function, no database) and
then the same rule as it surfaces through `find_alerts`, which is what the
prescription view consumes.
"""

import pytest

from models.enums import DrugAlertLevelEnum, DrugAlertTypeEnum
from services import alert_service
from tests.utils import utils_test_prescription

EXAMS = {"weight": 80, "age": 50}


class _PrescriptionDrug:
    """Minimal stand-in: _alert_max_time only reads `id` and `period`."""

    def __init__(self, period=None, id_prescription_drug=71):
        self.id = id_prescription_drug
        self.period = period


class _DrugAttributes:
    """Minimal stand-in: _alert_max_time only reads `maxTime`."""

    def __init__(self, max_time=None):
        self.maxTime = max_time


def _alert(period=None, max_time=None, is_cpoe=False, cpoe_period=None, attrs=True):
    """Call the helper with the given treatment period and configured limit."""
    return alert_service._alert_max_time(
        prescription_drug=_PrescriptionDrug(period=period),
        drug_attributes=_DrugAttributes(max_time=max_time) if attrs else None,
        is_cpoe=is_cpoe,
        cpoe_period=cpoe_period,
    )


class TestAlertMaxTimeHelper:
    """Tests for alert_service._alert_max_time."""

    def test_no_alert_without_drug_attributes(self):
        """A drug with no attributes row has no configured limit."""
        assert _alert(period=30, attrs=False) is None

    def test_no_alert_when_max_time_is_not_configured(self):
        """maxTime is optional; when unset the rule never fires."""
        assert _alert(period=30, max_time=None) is None

    def test_no_alert_when_max_time_is_zero(self):
        """A zero limit is treated as 'not configured', not as 'never allowed'."""
        assert _alert(period=30, max_time=0) is None

    def test_no_alert_without_a_period(self):
        """An item with no period yields a zero total, which never exceeds a limit."""
        assert _alert(period=None, max_time=7) is None

    def test_no_alert_below_the_limit(self):
        """Six days of treatment stay under a seven-day limit."""
        assert _alert(period=6, max_time=7) is None

    def test_no_alert_exactly_at_the_limit(self):
        """The comparison is strict: the limit itself is still acceptable."""
        assert _alert(period=7, max_time=7) is None

    def test_alert_above_the_limit(self):
        """One day past the limit raises the alert."""
        alert = _alert(period=8, max_time=7)

        assert alert is not None
        assert alert["type"] == DrugAlertTypeEnum.MAX_TIME.value
        assert alert["level"] == DrugAlertLevelEnum.HIGH.value
        assert alert["idPrescriptionDrug"] == "71"

    def test_alert_text_carries_both_periods(self):
        """The message names the current period and the configured maximum."""
        alert = _alert(period=12, max_time=7)

        assert "12 dias" in alert["text"]
        assert "7 dias" in alert["text"]

    def test_alert_text_renders_the_period_as_an_integer(self):
        """A fractional period is rounded down for display, not printed as a float."""
        alert = _alert(period=10.5, max_time=7)

        assert "10 dias" in alert["text"]
        assert "10.5" not in alert["text"]


class TestAlertMaxTimeCpoe:
    """The CPOE period is accumulated before being compared to the limit."""

    def test_cpoe_adds_one_day_when_the_item_has_no_previous_period(self):
        """A first CPOE day counts as cpoe_period + 1 (7 + 1 > 7)."""
        alert = _alert(period=None, max_time=7, is_cpoe=True, cpoe_period=7)

        assert alert is not None
        assert "8 dias" in alert["text"]

    def test_cpoe_sums_the_item_period_with_the_chain_period(self):
        """With a previous period the two are summed (4 + 5 > 7)."""
        alert = _alert(period=4, max_time=7, is_cpoe=True, cpoe_period=5)

        assert alert is not None
        assert "9 dias" in alert["text"]

    def test_cpoe_accumulation_can_stay_below_the_limit(self):
        """The accumulated total is still compared strictly (2 + 3 < 7)."""
        assert _alert(period=2, max_time=7, is_cpoe=True, cpoe_period=3) is None

    def test_same_item_does_not_alert_outside_cpoe(self):
        """Without CPOE only the item period counts, so the alert does not fire."""
        assert _alert(period=4, max_time=7, is_cpoe=False, cpoe_period=5) is None


def _find_alerts(drugs, is_cpoe=False):
    """Run the alert engine over a drug list with every other input neutral."""
    return alert_service.find_alerts(
        drug_list=drugs,
        exams=EXAMS,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
        cn_data=None,
        protocols=None,
        is_cpoe=is_cpoe,
    )


def test_max_time_alert_is_reported_per_drug():
    """find_alerts: each drug past its own limit gets one maxTime alert."""
    drugs = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=61, dose=10, frequency=1, period=10, max_time=7
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=62, dose=10, frequency=1, period=20, max_time=15
        ),
    ]

    alerts = _find_alerts(drugs)

    alert1 = alerts["alerts"].get("61", [])
    alert2 = alerts["alerts"].get("62", [])

    assert len(alert1) == 1
    assert len(alert2) == 1

    assert alert1[0]["type"] == DrugAlertTypeEnum.MAX_TIME.value
    assert alert2[0]["type"] == DrugAlertTypeEnum.MAX_TIME.value

    assert alert1[0]["level"] == DrugAlertLevelEnum.HIGH.value
    assert alert2[0]["level"] == DrugAlertLevelEnum.HIGH.value

    assert alerts["stats"].get(DrugAlertTypeEnum.MAX_TIME.value, 0) == 2


def test_max_time_alert_text_is_normalized():
    """find_alerts strips the indentation of the multi-line message template."""
    drugs = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=61, dose=10, frequency=1, period=10, max_time=7
        )
    ]

    text = _find_alerts(drugs)["alerts"]["61"][0]["text"]

    assert "\n" not in text
    assert "  " not in text
    assert "10 dias" in text
    assert "7 dias" in text


def test_no_max_time_alert_within_the_limit():
    """find_alerts: a drug inside its limit produces no alert at all."""
    drugs = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=61, dose=10, frequency=1, period=5, max_time=7
        )
    ]

    alerts = _find_alerts(drugs)

    assert alerts["alerts"].get("61", []) == []
    assert alerts["stats"].get(DrugAlertTypeEnum.MAX_TIME.value, 0) == 0


def test_no_max_time_alert_when_the_drug_has_no_limit():
    """find_alerts: a long treatment without a configured maxTime is silent."""
    drugs = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=61, dose=10, frequency=1, period=90
        )
    ]

    alerts = _find_alerts(drugs)

    assert alerts["alerts"].get("61", []) == []
    assert alerts["stats"].get(DrugAlertTypeEnum.MAX_TIME.value, 0) == 0


@pytest.mark.parametrize(
    "period, cpoe_period, expected_alert",
    [
        (None, 7, True),  # first CPOE day: 7 + 1 > 7
        (4, 5, True),  # accumulated: 4 + 5 > 7
        (2, 3, False),  # accumulated: 2 + 3 < 7
        (None, 6, False),  # first CPOE day: 6 + 1 == 7, still acceptable
    ],
)
def test_max_time_alert_uses_the_accumulated_cpoe_period(
    period, cpoe_period, expected_alert
):
    """find_alerts in CPOE mode compares the accumulated period to the limit."""
    drugs = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=61,
            dose=10,
            frequency=1,
            period=period,
            period_cpoe=cpoe_period,
            max_time=7,
        )
    ]

    alerts = _find_alerts(drugs, is_cpoe=True)
    reported = alerts["alerts"].get("61", [])

    assert bool(reported) == expected_alert
    if expected_alert:
        assert reported[0]["type"] == DrugAlertTypeEnum.MAX_TIME.value
