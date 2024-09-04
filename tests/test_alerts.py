from datetime import datetime
from collections import namedtuple

from conftest import *
from models.prescription import PrescriptionDrug, DrugAttributes, Drug, Frequency
from models.enums import DrugAlertTypeEnum, DrugAlertLevelEnum
from services import alert_service
from conftest import _get_mock_row

MockRow = namedtuple(
    "Mockrow",
    "prescription_drug drug measure_unit frequency not_used score drug_attributes notes prevnotes status expire substance period_cpoe prescription_date measure_unit_convert_factor",
)


def test_dosemaxplus():
    """Alertas dosemaxplus: Testa presença do alerta tipo dosemaxplus"""

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1, max_dose=10)
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, max_dose=10)
    )

    exams = {"age": 50, "weight": 80}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )

    stats = alerts.get("stats")
    dosemax1 = alerts.get("alerts").get("61", [])
    dosemax2 = alerts.get("alerts").get("62", [])

    assert len(dosemax1) == 1
    assert len(dosemax2) == 1

    assert dosemax1[0].get("type", None) == "maxDosePlus"
    assert dosemax2[0].get("type", None) == "maxDosePlus"

    assert dosemax1[0].get("level", None) == "high"
    assert dosemax2[0].get("level", None) == "high"

    assert stats.get("maxDosePlus", 0) == 2


@pytest.mark.parametrize(
    "doses, frequencies, max_dose, weight, use_weight, expire_dates, expected_alert",
    [
        (
            [10, 10],  # doses
            [2, 3],  # frequencies
            40,  # max_dose
            80,  # weight
            False,  # use_weight
            [datetime.now(), datetime.now()],  # expire_dates
            True,  # expected_alert
        ),
        (
            [5, 10],  # doses
            [2, 1],  # frequencies
            40,  # max_dose
            80,  # weight
            False,  # use_weight
            [datetime.now(), datetime.now()],  # expire_dates
            False,  # expected_alert
        ),
        (
            [0.3, 0.4],  # doses
            [2, 3],  # frequencies
            0.5,  # max_dose
            80,  # weight
            True,  # use_weight
            [datetime.now(), datetime.now()],  # expire_dates
            True,  # expected_alert
        ),
        (
            [0.1, 0.2],  # doses
            [2, 1],  # frequencies
            0.5,  # max_dose
            80,  # weight
            True,  # use_weight
            [datetime.now(), datetime.now()],  # expire_dates
            False,  # expected_alert
        ),
    ],
)
def test_max_dose_total_additional(
    doses, frequencies, max_dose, weight, use_weight, expire_dates, expected_alert
):
    drugs = [
        _get_mock_row(
            id_prescription_drug=i + 1,
            dose=dose,
            frequency=freq,
            max_dose=max_dose,
            use_weight=use_weight,
            expire_date=exp_date,
        )
        for i, (dose, freq, exp_date) in enumerate(
            zip(doses, frequencies, expire_dates)
        )
    ]
    exams = {"age": 50, "weight": weight}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )
    max_dose_total_alerts = [
        alert
        for alerts_list in alerts.get("alerts", {}).values()
        for alert in alerts_list
        if alert.get("type") == DrugAlertTypeEnum.MAX_DOSE_PLUS.value
    ]
    max_dose_total_alert_count = alerts.get("stats", {}).get(
        DrugAlertTypeEnum.MAX_DOSE_PLUS.value, 0
    )

    if expected_alert:
        assert len(max_dose_total_alerts) > 0
        assert (
            max_dose_total_alerts[0].get("type")
            == DrugAlertTypeEnum.MAX_DOSE_PLUS.value
        )
        assert max_dose_total_alerts[0].get("level") == DrugAlertLevelEnum.HIGH.value
        assert max_dose_total_alert_count > 0
    else:
        assert len(max_dose_total_alerts) == 0
        assert max_dose_total_alert_count == 0


def test_dosemax():
    """Alertas dosemaxplus: Testa presença do alerta tipo dosemax"""
    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=20, frequency=1, max_dose=10)
    )

    exams = {"age": 50, "weight": 80}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )

    stats = alerts.get("stats")
    dosemax1 = alerts.get("alerts").get("61", [])

    assert len(dosemax1) == 1

    assert dosemax1[0].get("type", None) == "maxDose"

    assert dosemax1[0].get("level", None) == "high"

    assert stats.get("maxDose", 0) == 1


@pytest.mark.parametrize(
    "dose, frequency, max_dose, weight, use_weight, expected_alert",
    [
        (20, 1, 10, 80, False, True),  # Dose exceeds max_dose
        (5, 1, 10, 80, False, False),  # Dose within max_dose
        (1, 1, 0.05, 80, True, True),  # Dose/kg exceeds max_dose/kg
        (0.02, 1, 0.05, 80, True, False),  # Dose/kg within max_dose/kg
        (20, 2, 30, 80, False, True),  # Daily dose (20*2) exceeds max_dose
        (10, 2, 30, 80, False, False),  # Daily dose (10*2) within max_dose
    ],
)
def test_max_dose_additional(
    dose, frequency, max_dose, weight, use_weight, expected_alert
):
    drugs = [
        _get_mock_row(
            id_prescription_drug=61,
            dose=dose,
            frequency=frequency,
            max_dose=max_dose,
            use_weight=use_weight,
        )
    ]
    exams = {"age": 50, "weight": weight}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )

    max_dose_alerts = alerts.get("alerts", {}).get("61", [])
    max_dose_alert_count = alerts.get("stats", {}).get(
        DrugAlertTypeEnum.MAX_DOSE.value, 0
    )

    if expected_alert:
        assert len(max_dose_alerts) == 1
        assert max_dose_alerts[0].get("type") == DrugAlertTypeEnum.MAX_DOSE.value
        assert max_dose_alerts[0].get("level") == DrugAlertLevelEnum.HIGH.value
        assert max_dose_alert_count == 1
    else:
        assert len(max_dose_alerts) == 0
        assert max_dose_alert_count == 0


def test_kidney_dialysis():
    """Kidney alerts:  Test for the presence of an alert type equal to 'kidney' with dialysis"""

    drugs = []

    drugs.append(
        _get_mock_row(
            id_prescription_drug=61, dose=10, frequency=1, max_dose=20, kidney=True
        )
    )
    drugs.append(
        _get_mock_row(
            id_prescription_drug=62, dose=10, frequency=1, max_dose=20, kidney=True
        )
    )

    exams = {"age": 50, "weight": 80}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys="c",
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )
    stats = alerts.get("stats")

    alert1 = alerts.get("alerts").get("61", [])
    alert2 = alerts.get("alerts").get("62", [])

    assert len(alert1) == 1
    assert len(alert2) == 1

    assert alert1[0].get("type", None) == "kidney"
    assert alert2[0].get("type", None) == "kidney"

    assert alert1[0].get("level", None) == "medium"
    assert alert2[0].get("level", None) == "medium"

    assert stats.get("kidney", 0) == 2


def test_kidney_ckd():
    """Kidney alerts:  Test for the presence of an alert type equal to 'kidney' CKD"""

    drugs = []

    drugs.append(
        _get_mock_row(
            id_prescription_drug=61, dose=10, frequency=1, max_dose=20, kidney=10
        )
    )

    exams = {"age": 50, "weight": 80, "ckd": {"value": 5}}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )
    stats = alerts.get("stats")

    alert1 = alerts.get("alerts").get("61", [])

    assert len(alert1) == 1

    assert alert1[0].get("type", None) == "kidney"

    assert alert1[0].get("level", None) == "medium"

    assert stats.get("kidney", 0) == 1


def test_kidney_swrtz2():
    """Kidney alerts:  Test for the presence of an alert type equal to 'kidney' swrtz2"""

    drugs = []

    drugs.append(
        _get_mock_row(
            id_prescription_drug=61, dose=10, frequency=1, max_dose=20, kidney=10
        )
    )

    exams = {"age": 17, "weight": 80, "swrtz2": {"value": 5}}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )
    stats = alerts.get("stats")

    alert1 = alerts.get("alerts").get("61", [])

    assert len(alert1) == 1

    assert alert1[0].get("type", None) == "kidney"

    assert alert1[0].get("level", None) == "medium"

    assert stats.get("kidney", 0) == 1


def test_kidney_swrtz1():
    """Kidney alerts:  Test for the presence of an alert type equal to 'kidney' swrtz1"""

    drugs = []

    drugs.append(
        _get_mock_row(
            id_prescription_drug=61, dose=10, frequency=1, max_dose=20, kidney=10
        )
    )

    exams = {"age": 17, "weight": 80, "swrtz1": {"value": 5}}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )
    stats = alerts.get("stats")

    alert1 = alerts.get("alerts").get("61", [])

    assert len(alert1) == 1

    assert alert1[0].get("type", None) == "kidney"

    assert alert1[0].get("level", None) == "medium"

    assert stats.get("kidney", 0) == 1


@pytest.mark.parametrize(
    "kidney_threshold, ckd_value, age, dialysis, expected_alert",
    [
        (60, 50, 18, None, True),  # Adult, CKD below threshold
        (60, 70, 18, None, False),  # Adult, CKD above threshold
        (60, 70, 18, "c", True),  # Continuous dialysis
        (60, 70, 18, "x", True),  # Extended dialysis
        (60, 70, 18, "v", True),  # Intermittent dialysis
        (60, 70, 18, "p", True),  # Peritoneal dialysis
    ],
)
def test_kidney_alert_multiple(
    kidney_threshold, ckd_value, age, dialysis, expected_alert
):

    drugs = [
        _get_mock_row(id_prescription_drug=1, dose=ckd_value, kidney=kidney_threshold)
    ]
    exams = {
        "age": age,
        "weight": 80,
        "ckd": {"value": ckd_value} if ckd_value is not None else None,
    }
    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=dialysis,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )
    kidney_alerts = alerts.get("alerts", {}).get("1", [])
    kidney_alert_count = alerts.get("stats", {}).get(DrugAlertTypeEnum.KIDNEY.value, 0)

    if expected_alert:
        assert len(kidney_alerts) == 1
        assert kidney_alerts[0].get("type") == DrugAlertTypeEnum.KIDNEY.value
        assert kidney_alerts[0].get("level") == DrugAlertLevelEnum.MEDIUM.value
        assert kidney_alert_count == 1
    else:
        assert len(kidney_alerts) == 0
        assert kidney_alert_count == 0


def test_liver():
    """Liver alerts:  Test for the presence of an alert type equal to 'liver'"""

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1, liver=1.1)
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, liver=1.1)
    )

    exams = {"tgp": {"value": 3.0}, "weight": 80}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )
    stats = alerts.get("stats")

    alert1 = alerts.get("alerts").get("61", [])
    alert2 = alerts.get("alerts").get("62", [])

    assert len(alert1) == 1
    assert len(alert2) == 1

    assert alert1[0].get("type", None) == "liver"
    assert alert2[0].get("type", None) == "liver"

    assert alert1[0].get("level", None) == "medium"
    assert alert2[0].get("level", None) == "medium"

    assert stats.get("liver", 0) == 2


def test_platelets():
    """Platelets alerts:  Test for the presence of an alert type equal to 'platelets'"""

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1, platelets=10.1)
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, platelets=10.1)
    )

    exams = {"plqt": {"value": 3.0}, "weight": 80}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )
    stats = alerts.get("stats")

    alert1 = alerts.get("alerts").get("61", [])
    alert2 = alerts.get("alerts").get("62", [])

    assert len(alert1) == 1
    assert len(alert2) == 1

    assert alert1[0].get("type", None) == "platelets"
    assert alert2[0].get("type", None) == "platelets"

    assert alert1[0].get("level", None) == "high"
    assert alert2[0].get("level", None) == "high"

    assert stats.get("platelets", 0) == 2


def test_elderly():
    """Elderly alerts:  Test for the presence of an alert type equal to 'elderly'"""

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1, elderly=True)
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, elderly=True)
    )
    exams = {"weight": 80, "age": 68}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )

    stats = alerts.get("stats")

    alert1 = alerts.get("alerts").get("61", [])
    alert2 = alerts.get("alerts").get("62", [])

    assert len(alert1) == 1
    assert len(alert2) == 1

    assert alert1[0].get("type", None) == "elderly"
    assert alert2[0].get("type", None) == "elderly"

    assert alert1[0].get("level", None) == "low"
    assert alert2[0].get("level", None) == "low"

    assert stats.get("elderly", 0) == 2


def test_tube():
    """Tube alerts:  Test for the presence of an alert type equal to 'tube'"""

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1, tube=True)
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, tube=True)
    )
    exams = {"weight": 80, "tube": True}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )

    stats = alerts.get("stats")

    alert1 = alerts.get("alerts").get("61", [])
    alert2 = alerts.get("alerts").get("62", [])

    assert len(alert1) == 1
    assert len(alert2) == 1

    assert alert1[0].get("type", None) == "tube"
    assert alert2[0].get("type", None) == "tube"

    assert alert1[0].get("level", None) == "high"
    assert alert2[0].get("level", None) == "high"

    assert stats.get("tube", 0) == 2


def test_allergy():
    """Allergy alerts:  Test for the presence of an alert type equal to 'allergy'"""

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1, allergy="S")
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, allergy="S")
    )
    exams = {"weight": 80}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )

    stats = alerts.get("stats")

    alert1 = alerts.get("alerts").get("61", [])
    alert2 = alerts.get("alerts").get("62", [])

    assert len(alert1) == 1
    assert len(alert2) == 1

    assert alert1[0].get("type", None) == "allergy"
    assert alert2[0].get("type", None) == "allergy"

    assert alert1[0].get("level", None) == "high"
    assert alert2[0].get("level", None) == "high"

    assert stats.get("allergy", 0) == 2


# simple ira alert test, single condition
def test_ira():
    """IRA alerts:  Test for the presence of an alert type equal to 'ira' - Insuficiência Renal Aguda"""

    drugs = []
    drugs.append(
        _get_mock_row(
            id_prescription_drug=61, dose=10, frequency=10, drug_name="xxx vancoyyy"
        )
    )

    exams = {"ckd": {"value": 1.0}, "weight": 80}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )

    stats = alerts.get("stats")
    alert1 = alerts.get("alerts").get("61", [])

    assert len(alert1) == 1

    assert alert1[0].get("type", None) == "ira"
    assert alert1[0].get("level", None) == "high"

    assert stats.get("ira", 0) == 1


###  TESTS FOR ALERT IRA CONDITIONS - MULTIPLE SCENARIOS
# input data
# dose, ckd, weight, dialysis = test_input
@pytest.mark.parametrize(
    "test_input,expected_alert",
    [
        ((3000, 40, 70, None), True),  # Should trigger alert (baseline case)
        ((2000, 50, 70, None), False),  # Should not trigger alert (below threshold)
        ((4000, 30, 60, None), True),  # Should trigger alert (high dose, low CKD)
        ((3000, 40, 70, "c"), False),  # Should not trigger alert (patient on dialysis)
        ((3000, 0, 70, None), False),  # Should not trigger alert (CKD is 0)
        ((3000, 40, 0, None), False),  # Should not trigger alert (weight is 0)
        ((1000, 20, 50, None), True),  # Should trigger alert (low dose, very low CKD)
    ],
)
def test_ira_alert_conditions(test_input, expected_alert):
    """IRA alerts: Test various conditions for triggering or not triggering the IRA alert"""
    dose, ckd, weight, dialysis = test_input

    drugs = []
    drugs.append(
        _get_mock_row(
            id_prescription_drug=61, dose=dose, frequency=1, drug_name="Vancomicina"
        )
    )

    exams = {"ckd": {"value": ckd}, "weight": weight}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=dialysis,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
    )

    alert1 = alerts.get("alerts", {}).get("61", [])

    if expected_alert:
        assert len(alert1) == 1, f"Expected 1 alert, but got {len(alert1)}"
        assert (
            alert1[0].get("type") == "ira"
        ), f"Expected alert type 'ira', but got {alert1[0].get('type')}"
        assert (
            alert1[0].get("level") == "high"
        ), f"Expected alert level 'high', but got {alert1[0].get('level')}"
        assert (
            alerts.get("stats", {}).get("ira", 0) == 1
        ), f"Expected 1 IRA alert in stats, but got {alerts.get('stats', {}).get('ira', 0)}"
        assert "Risco de desenvolvimento de Insuficiência Renal Aguda (IRA)" in alert1[
            0
        ].get("text", ""), "Expected IRA risk message in alert text"
    else:
        assert len(alert1) == 0, f"Expected no alerts, but got {len(alert1)}"
        assert (
            alerts.get("stats", {}).get("ira", 0) == 0
        ), f"Expected 0 IRA alerts in stats, but got {alerts.get('stats', {}).get('ira', 0)}"


def test_pregnant():
    """Pregnant alerts:  Test for the presence of an alert type equal to 'pregnant'"""

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1, pregnant="D")
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, pregnant="X")
    )

    exams = {"weight": 80}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=True,
        lactating=None,
        schedules_fasting=None,
    )

    stats = alerts.get("stats")

    alert1 = alerts.get("alerts").get("61", [])
    alert2 = alerts.get("alerts").get("62", [])

    assert len(alert1) == 1
    assert len(alert2) == 1

    assert alert1[0].get("type", None) == "pregnant"
    assert alert2[0].get("type", None) == "pregnant"

    assert alert1[0].get("level", None) == "medium"
    assert alert2[0].get("level", None) == "high"

    assert stats.get("pregnant", 0) == 2


def test_lactating():
    """Lactating alerts:  Test for the presence of an alert type equal to 'lactating'"""

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1, lactating="3")
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, lactating="3")
    )

    exams = {"weight": 80}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=True,
        schedules_fasting=None,
    )

    stats = alerts.get("stats")

    alert1 = alerts.get("alerts").get("61", [])
    alert2 = alerts.get("alerts").get("62", [])

    assert len(alert1) == 1
    assert len(alert2) == 1

    assert alert1[0].get("type", None) == "lactating"
    assert alert2[0].get("type", None) == "lactating"

    assert alert1[0].get("level", None) == "medium"
    assert alert2[0].get("level", None) == "medium"

    assert stats.get("lactating", 0) == 2


def test_fasting():
    """Fasting alerts:  Test for the presence of an alert type equal to 'fasting'"""

    drugs = []

    freq_obj = Frequency()
    freq_obj.id = 111
    freq_obj.fasting = False

    drugs.append(
        _get_mock_row(
            id_prescription_drug=61, dose=10, interval="12", freq_obj=freq_obj
        )
    )

    exams = {"weight": 80}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=["8", "24"],
    )

    stats = alerts.get("stats")
    alert1 = alerts.get("alerts").get("61", [])

    assert len(alert1) == 1

    assert alert1[0].get("type", None) == "fasting"

    assert alert1[0].get("level", None) == "medium"

    assert stats.get("fasting", 0) == 1
