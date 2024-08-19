from datetime import datetime
from collections import namedtuple

from conftest import *
from models.prescription import PrescriptionDrug, DrugAttributes, Drug
from services import alert_service

MockRow = namedtuple(
    "Mockrow",
    "prescription_drug drug measure_unit frequency not_used score drug_attributes notes prevnotes status expire substance period_cpoe prescription_date measure_unit_convert_factor",
)


def _get_mock_row(
    id_prescription_drug: int, dose: float, frequency: float, max_dose: float = None
):
    d = Drug()
    d.id = 1
    d.name = "Test2"

    pd = PrescriptionDrug()
    pd.id = id_prescription_drug
    pd.source = "Medicamentos"
    pd.idDrug = 1
    pd.frequency = frequency
    pd.doseconv = dose

    da = DrugAttributes()
    da.idDrug = 1
    da.idSegment = 1
    da.maxDose = max_dose

    return MockRow(
        pd,
        d,
        None,
        None,
        None,
        None,
        da,
        None,
        None,
        None,
        datetime.today(),
        None,
        0,
        datetime.today(),
        1,
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
