"""Unit tests: maximum dose alerts expressed per kilogram of body weight.

A drug registered with ``useWeight`` has its maximum dose configured in
``unit/Kg``, so both dose alerts must divide the prescribed daily dose by the
patient's weight before comparing it with the limit:

* ``maxDose`` — the daily dose of a single prescribed item;
* ``maxDosePlus`` — the daily dose summed across every item of the same drug
  on the same day.

The per-kg comparison only runs when the raw prescribed dose is filled, and it
falls back to a "fill in the weight" message when the patient has no weight
recorded (the dose is then compared as if the patient weighed 1 Kg, which is
the worst case and always raises the alert).
"""

import pytest

from services import alert_service
from tests.utils import utils_test_prescription

# doseconv x frequency = 20 units/day for every drug built below
DOSE = 10
FREQUENCY = 2
DAILY_DOSE = DOSE * FREQUENCY
WEIGHT = 80
# 20 units/day for a 80 Kg patient
DAILY_DOSE_PER_KG = DAILY_DOSE / WEIGHT  # 0.25
MISSING_WEIGHT_MESSAGE = (
    "A dose máxima registrada é por kg, mas o peso do paciente não está "
    "disponível. Favor preencher manualmente o peso."
)


def _drug(id_prescription_drug: int, max_dose: float, use_weight=True, dose=DOSE):
    """Build a prescribed drug whose daily dose is dose x FREQUENCY."""
    return utils_test_prescription.get_prescription_drug_mock_row(
        id_prescription_drug=id_prescription_drug,
        dose=dose,
        prescribed_dose=dose,
        frequency=FREQUENCY,
        max_dose=max_dose,
        use_weight=use_weight,
    )


def _find_alerts(drugs, weight=WEIGHT):
    """Run the alert engine over the drugs for a patient with the given weight."""
    return alert_service.find_alerts(
        drug_list=drugs,
        exams={"age": 50, "weight": weight},
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
        cn_data=None,
        protocols=None,
        is_cpoe=False,
    )


def _alerts_of_type(alerts: dict, id_prescription_drug: int, alert_type: str):
    """Return the alerts of one type raised for a single prescribed drug."""
    return [
        a
        for a in alerts.get("alerts").get(str(id_prescription_drug), [])
        if a.get("type") == alert_type
    ]


def test_max_dose_alert_compares_the_dose_per_kilogram():
    """The limit of a useWeight drug is read as unit/Kg, not as an absolute dose"""
    alerts = _find_alerts([_drug(71, max_dose=0.1)])

    max_dose = _alerts_of_type(alerts, 71, "maxDose")

    assert len(max_dose) == 1
    assert max_dose[0]["level"] == "high"
    assert "/Kg" in max_dose[0]["text"]
    # the prescribed dose is reported per kilogram, not as the raw daily dose
    assert "0,25" in max_dose[0]["text"]
    assert alerts.get("stats").get("maxDose") == 1


def test_no_max_dose_alert_when_the_dose_per_kilogram_is_within_the_limit():
    """A dose above the limit in absolute terms is still fine once divided by the weight"""
    # 20 units/day is way above 1, but 0.25 unit/Kg/day is not
    assert DAILY_DOSE > 1 > DAILY_DOSE_PER_KG

    alerts = _find_alerts([_drug(72, max_dose=1)])

    assert _alerts_of_type(alerts, 72, "maxDose") == []
    assert alerts.get("stats").get("maxDose") == 0


@pytest.mark.parametrize("weight", [None, 0])
def test_max_dose_alert_asks_for_the_weight_when_it_is_missing(weight):
    """Without a weight the alert explains that the limit is per kg and must be checked"""
    alerts = _find_alerts([_drug(73, max_dose=0.1)], weight=weight)

    max_dose = _alerts_of_type(alerts, 73, "maxDose")

    assert len(max_dose) == 1
    assert max_dose[0]["text"] == MISSING_WEIGHT_MESSAGE


def test_max_dose_per_kilogram_needs_the_prescribed_dose():
    """With no raw dose there is nothing to divide, so the absolute limit is used"""
    drug = utils_test_prescription.get_prescription_drug_mock_row(
        id_prescription_drug=74,
        dose=DOSE,
        prescribed_dose=None,
        frequency=FREQUENCY,
        max_dose=1,
        use_weight=True,
    )

    max_dose = _alerts_of_type(_find_alerts([drug]), 74, "maxDose")

    assert len(max_dose) == 1
    assert "/Kg" not in max_dose[0]["text"]


def test_max_dose_total_alert_sums_the_dose_per_kilogram():
    """Two items of the same drug are summed per kg before hitting the limit"""
    # 0.25 + 0.25 = 0.5 unit/Kg/day, above the 0.3 limit
    alerts = _find_alerts([_drug(75, max_dose=0.3), _drug(76, max_dose=0.3)])

    for id_prescription_drug in (75, 76):
        max_dose_plus = _alerts_of_type(alerts, id_prescription_drug, "maxDosePlus")

        assert len(max_dose_plus) == 1
        assert max_dose_plus[0]["level"] == "high"
        assert "/Kg" in max_dose_plus[0]["text"]
        assert "SOMADA" in max_dose_plus[0]["text"]

    assert alerts.get("stats").get("maxDosePlus") == 2
    # each item on its own (0.25 unit/Kg) stays below the limit
    assert alerts.get("stats").get("maxDose") == 0


def test_no_max_dose_total_alert_when_the_summed_dose_per_kilogram_is_within_the_limit():
    """The summed limit is also read per kg: 0.5 unit/Kg/day is below a 0.6 limit"""
    alerts = _find_alerts([_drug(77, max_dose=0.6), _drug(78, max_dose=0.6)])

    assert _alerts_of_type(alerts, 77, "maxDosePlus") == []
    assert _alerts_of_type(alerts, 78, "maxDosePlus") == []
    assert alerts.get("stats").get("maxDosePlus") == 0


def test_max_dose_total_alert_asks_for_the_weight_when_it_is_missing():
    """Without a weight the summed alert also asks for it to be filled in"""
    alerts = _find_alerts(
        [_drug(79, max_dose=0.3), _drug(80, max_dose=0.3)], weight=None
    )

    for id_prescription_drug in (79, 80):
        max_dose_plus = _alerts_of_type(alerts, id_prescription_drug, "maxDosePlus")

        assert len(max_dose_plus) == 1
        assert max_dose_plus[0]["text"] == MISSING_WEIGHT_MESSAGE


def test_max_dose_total_per_kilogram_needs_more_than_one_prescribed_item():
    """A single item never raises the summed alert, however high its dose per kg is"""
    alerts = _find_alerts([_drug(81, max_dose=0.1)])

    assert _alerts_of_type(alerts, 81, "maxDosePlus") == []
    # the single-item alert is still raised
    assert len(_alerts_of_type(alerts, 81, "maxDose")) == 1
