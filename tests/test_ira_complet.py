import pytest
from services import alert_service
from datetime import datetime
from collections import namedtuple

from conftest import *
from models.prescription import PrescriptionDrug, DrugAttributes, Drug,Frequency

import pytest
from services import alert_service

def _get_mock_row(
    id_prescription_drug: int, dose: float, frequency: float = None, max_dose: float = None,kidney: bool = None,
    liver: float = None, platelets: float = None, elderly: bool = None, tube: bool = None, allergy: str = None,
    drug_name : str = "Test2", pregnant : str = None, lactating: str = None, interval: str = None, freq_obj:Frequency = None,
):
    
    MockRow = namedtuple(
    "Mockrow",
    "prescription_drug drug measure_unit frequency not_used score drug_attributes notes prevnotes status expire substance period_cpoe prescription_date measure_unit_convert_factor",
)
    
    d = Drug()
    d.id = 1
    d.name = drug_name 

    pd = PrescriptionDrug()
    pd.id = id_prescription_drug
    pd.source = "Medicamentos"
    pd.idDrug = 1
    pd.frequency = frequency
    pd.doseconv = dose
    pd.tube = tube
    pd.allergy = allergy
    pd.interval = interval

    da = DrugAttributes()
    da.idDrug = 1
    da.idSegment = 1
    da.maxDose = max_dose
    da.kidney = kidney
    da.liver =  liver
    da.platelets = platelets
    da.elderly = elderly
    da.tube = tube
    da.pregnant = pregnant
    da.lactating = lactating
    da.fasting = True

    return MockRow(
        pd,
        d,
        None,
        freq_obj,
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

# input data 
# dose, ckd, weight, dialysis = test_input
@pytest.mark.parametrize("test_input,expected_alert", [
    ((3000, 40, 70, None), True),  # Should trigger alert (baseline case)
    ((2000, 50, 70, None), False),  # Should not trigger alert (below threshold)
    ((4000, 30, 60, None), True),  # Should trigger alert (high dose, low CKD)
    ((3000, 40, 70, 'c'), False),  # Should not trigger alert (patient on dialysis)
    ((3000, 0, 70, None), False),  # Should not trigger alert (CKD is 0)
    ((3000, 40, 0, None), False),  # Should not trigger alert (weight is 0)
    ((1000, 20, 50, None), True),  # Should trigger alert (low dose, very low CKD)
])
def test_ira_alert_conditions(test_input, expected_alert):
    """IRA alerts: Test various conditions for triggering or not triggering the IRA alert"""
    dose, ckd, weight, dialysis = test_input

    drugs = []
    drugs.append(
        _get_mock_row(
            id_prescription_drug=61,
            dose=dose,
            frequency=1,
            drug_name="Vancomicina"
        )
    )

    exams = {'ckd': {'value': ckd}, 'weight': weight}

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
        assert alert1[0].get("type") == "ira", f"Expected alert type 'ira', but got {alert1[0].get('type')}"
        assert alert1[0].get("level") == "high", f"Expected alert level 'high', but got {alert1[0].get('level')}"
        assert alerts.get("stats", {}).get("ira", 0) == 1, f"Expected 1 IRA alert in stats, but got {alerts.get('stats', {}).get('ira', 0)}"
        assert "Risco de desenvolvimento de Insuficiência Renal Aguda (IRA)" in alert1[0].get("text", ""), "Expected IRA risk message in alert text"
    else:
        assert len(alert1) == 0, f"Expected no alerts, but got {len(alert1)}"
        assert alerts.get("stats", {}).get("ira", 0) == 0, f"Expected 0 IRA alerts in stats, but got {alerts.get('stats', {}).get('ira', 0)}"

