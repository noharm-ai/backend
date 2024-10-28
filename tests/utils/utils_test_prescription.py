from collections import namedtuple
from datetime import datetime, timedelta

from tests.conftest import session, session_commit
from models.prescription import (
    Prescription,
    PrescriptionDrug,
    DrugAttributes,
    Drug,
    Frequency,
    PrescriptionAudit,
)


def prepare_test_aggregate(id, admissionNumber, prescriptionid1, prescriptionid2):
    """Deleção da prescrição agregada já existente."""

    session.query(Prescription).filter(Prescription.id == id).delete()
    session_commit()

    """Deleção dos registros das prescrições."""

    session.query(PrescriptionAudit).filter(
        PrescriptionAudit.admissionNumber == admissionNumber
    ).delete()
    session_commit()

    """Mudança para status 0 nas prescrições id=4 e id=7."""

    session.query(Prescription).filter(
        Prescription.id.in_([prescriptionid1, prescriptionid2])
    ).update({"status": "0"}, synchronize_session="fetch")
    session_commit()


def get_prescription_drug_mock_row(
    id_prescription_drug: int,
    dose: float,
    frequency: float = None,
    max_dose: float = None,
    kidney: float = None,
    liver: float = None,
    platelets: float = None,
    elderly: bool = None,
    tube: bool = None,
    allergy: str = None,
    drug_name: str = "Test2",
    pregnant: str = None,
    lactating: str = None,
    interval: str = None,
    freq_obj: Frequency = None,
    use_weight: bool = False,
    expire_date: datetime = None,
    intravenous: bool = False,
    group: str = None,
    solutionGroup: bool = False,
    idPrescription: str = None,
):
    MockRow = namedtuple(
        "Mockrow",
        "prescription_drug drug measure_unit frequency not_used score drug_attributes notes prevnotes status expire substance period_cpoe prescription_date measure_unit_convert_factor substance_handling_types",
    )

    d = Drug()
    d.id = id_prescription_drug
    d.name = drug_name
    d.sctid = f"{id_prescription_drug}11111"  # Generate a unique sctid

    pd = PrescriptionDrug()
    pd.id = id_prescription_drug
    pd.source = "Medicamentos"
    pd.idDrug = 1
    pd.frequency = frequency
    pd.doseconv = dose
    pd.tube = tube
    pd.allergy = allergy
    pd.interval = interval
    pd.intravenous = intravenous
    pd.group = group
    pd.solutionGroup = solutionGroup
    pd.idPrescription = idPrescription

    da = DrugAttributes()
    da.idDrug = id_prescription_drug
    da.idSegment = 1
    da.maxDose = max_dose
    da.kidney = kidney
    da.liver = liver
    da.platelets = platelets
    da.elderly = elderly
    da.tube = tube
    da.pregnant = pregnant
    da.lactating = lactating
    da.fasting = True
    da.useWeight = use_weight

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
        expire_date or datetime.now() + timedelta(days=1),
        None,
        0,
        datetime.now(),
        1,
        [],
    )
