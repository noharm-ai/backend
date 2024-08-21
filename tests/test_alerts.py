from datetime import datetime
from collections import namedtuple

from conftest import *
from models.prescription import PrescriptionDrug, DrugAttributes, Drug,Frequency
from services import alert_service

MockRow = namedtuple(
    "Mockrow",
    "prescription_drug drug measure_unit frequency not_used score drug_attributes notes prevnotes status expire substance period_cpoe prescription_date measure_unit_convert_factor",
)

def _get_mock_row(
    id_prescription_drug: int, dose: float, frequency: float = None, max_dose: float = None,kidney: bool = None,
    liver: float = None, platelets: float = None, elderly: bool = None, tube: bool = None, allergy: str = None,
    drug_name : str = "Test2", pregnant : str = None, lactating: str = None, interval: str = None, freq_obj:Frequency = None,
):
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
    
def test_kidney():
    """Kidney alerts:  Test for the presence of an alert type equal to 'kidney' """

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1, max_dose=20,kidney = True)
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, max_dose=20,kidney = True)
    )

    exams = {"age": 50, "weight": 80}

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys='c',
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


def test_liver():
    """Liver alerts:  Test for the presence of an alert type equal to 'liver' """

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1,liver = 1.1)
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, liver = 1.1)
    )

    exams = {'tgp' : {'value' : 3.} , 'weight': 80 }

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
    """Platelets alerts:  Test for the presence of an alert type equal to 'platelets' """

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1,platelets = 10.1)
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, platelets = 10.1)
    )

    exams = {'plqt' : {'value' : 3.} , 'weight': 80 }

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
    """Elderly alerts:  Test for the presence of an alert type equal to 'elderly' """

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1,elderly = True)
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, elderly = True)
    )
    exams = { 'weight': 80 , 'age' : 68}

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
    """Tube alerts:  Test for the presence of an alert type equal to 'tube' """

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1,tube = True)
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, tube = True)
    )
    exams = { 'weight': 80 , 'tube' : True}

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
    """Allergy alerts:  Test for the presence of an alert type equal to 'allergy' """

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1,allergy = "S")
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1, allergy = "S")
    )
    exams = { 'weight': 80 }

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys= None,
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
    

def test_ira():
    """Fasting alerts:  Test for the presence of an alert type equal to 'ira' - Insuficiência Renal Aguda"""

    drugs =[]
    drugs.append(
       _get_mock_row(id_prescription_drug=61,dose=10, frequency=10,drug_name = "xxx vancoyyy")
    )

    exams = {'ckd' : {'value' : 1.}, 'weight': 80 }

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys= None,
        pregnant=None,
        lactating=None,
        schedules_fasting= None,
    )

    stats = alerts.get("stats")
    alert1 = alerts.get("alerts").get("61", [])
    
    assert len(alert1) == 1
   
    assert alert1[0].get("type", None) == "ira"
    assert alert1[0].get("level", None) == "high"
    
    assert stats.get("ira", 0) == 1   
    
    
def test_pregnant():
    """Pregnant alerts:  Test for the presence of an alert type equal to 'pregnant' """

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1,pregnant= "D")
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1,pregnant= "X")
    )
 
    exams = { 'weight': 80 }

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys= None,
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
    """Lactating alerts:  Test for the presence of an alert type equal to 'lactating' """

    drugs = []

    drugs.append(
        _get_mock_row(id_prescription_drug=61, dose=10, frequency=1,lactating= "3")
    )
    drugs.append(
        _get_mock_row(id_prescription_drug=62, dose=10, frequency=1,lactating= "3")
    )

    exams = { 'weight': 80 }

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys= None,
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
    """Fasting alerts:  Test for the presence of an alert type equal to 'fasting' """

    drugs = []
    
    freq_obj = Frequency()
    freq_obj.id = 111
    freq_obj.fasting = False
    
    drugs.append(
       _get_mock_row(id_prescription_drug=61,dose=10, interval= "12",freq_obj=freq_obj)
    )

    exams = { 'weight': 80 }

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys= None,
        pregnant=None,
        lactating=None,
        schedules_fasting= ["8","24"],
    )

    stats = alerts.get("stats")
    alert1 = alerts.get("alerts").get("61", [])

    assert len(alert1) == 1
  
    assert alert1[0].get("type", None) == "fasting"

    assert alert1[0].get("level", None) == "medium"
   
    assert stats.get("fasting", 0) == 1