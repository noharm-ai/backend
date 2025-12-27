from collections import namedtuple
from datetime import datetime, timedelta

from models.appendix import Frequency, MeasureUnit
from models.main import Drug, DrugAttributes, Substance
from models.prescription import (
    Prescription,
    PrescriptionAudit,
    PrescriptionDrug,
)
from tests.conftest import session, session_commit


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
    drug_class: str = None,
    sctid: str = None,
    route: str = None,
    period: int = None,
    notes: str = None,
    measure_unit_nh: str = None,
):
    MockRow = namedtuple(
        "Mockrow",
        "prescription_drug drug measure_unit frequency not_used score drug_attributes notes prevnotes status expire substance period_cpoe prescription_date measure_unit_convert_factor substance_handling_types",
    )

    sctid = (
        sctid if sctid else f"{id_prescription_drug}11111"
    )  # Generate a unique sctid
    d = Drug()
    d.id = id_prescription_drug
    d.name = drug_name
    d.sctid = sctid

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
    pd.route = route
    pd.period = period
    pd.notes = notes

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

    substance = Substance()
    substance.id = sctid
    substance.idclass = drug_class

    measure_unit = MeasureUnit()
    measure_unit.id = 1
    measure_unit.measureunit_nh = measure_unit_nh

    return MockRow(
        pd,
        d,
        measure_unit,
        freq_obj,
        None,
        None,
        da,
        None,
        None,
        None,
        expire_date or datetime.now() + timedelta(days=1),
        substance,
        0,
        datetime.now(),
        1,
        [],
    )


def create_prescription(
    id: int,
    admissionNumber: int,
    idPatient: int,
    idHospital: int = 1,
    idDepartment: int = 1,
    idSegment: int = 1,
    date: datetime = None,
    expire: datetime = None,
    status: str = "0",
    bed: str = "101",
    record: str = None,
    prescriber: str = "Dr. Test",
    insurance: str = None,
    agg: bool = None,
    concilia: str = None,
    user: int = 1,
):
    """Create a Prescription record for testing."""
    prescription = Prescription()
    prescription.id = id
    prescription.admissionNumber = admissionNumber
    prescription.idHospital = idHospital
    prescription.idDepartment = idDepartment
    prescription.idSegment = idSegment
    prescription.idPatient = idPatient
    prescription.date = date or datetime.now()
    prescription.expire = expire or (datetime.now() + timedelta(days=1))
    prescription.status = status
    prescription.bed = bed
    prescription.record = record
    prescription.prescriber = prescriber
    prescription.insurance = insurance
    prescription.agg = agg
    prescription.concilia = concilia
    prescription.user = user

    session.add(prescription)
    session_commit()

    return prescription


def create_prescription_drug(
    id: int,
    idPrescription: int,
    idDrug: int,
    idMeasureUnit: str = "mg",
    idFrequency: str = "1x",
    dose: float = 100.0,
    doseconv: float = None,
    frequency: float = 1.0,
    route: str = "VO",
    interval: str = None,
    source: str = "Medicamentos",
    idSegment: int = 1,
    tube: bool = False,
    allergy: str = None,
    intravenous: bool = False,
    solutionGroup: int = None,
    cpoe_group: str = None,
    period: int = None,
    notes: str = None,
    checked: bool = False,
    suspendedDate: datetime = None,
    status: str = "0",
    near: bool = False,
    schedule: str = None,
    order_number: int = None,
):
    """Create a PrescriptionDrug record for testing."""
    prescription_drug = PrescriptionDrug()
    prescription_drug.id = id
    prescription_drug.idPrescription = idPrescription
    prescription_drug.idDrug = idDrug
    prescription_drug.idMeasureUnit = idMeasureUnit
    prescription_drug.idFrequency = idFrequency
    prescription_drug.dose = dose
    prescription_drug.doseconv = doseconv or dose
    prescription_drug.frequency = frequency
    prescription_drug.route = route
    prescription_drug.interval = interval
    prescription_drug.source = source
    prescription_drug.idSegment = idSegment
    prescription_drug.tube = tube
    prescription_drug.allergy = allergy
    prescription_drug.intravenous = intravenous
    prescription_drug.solutionGroup = solutionGroup
    prescription_drug.cpoe_group = cpoe_group
    prescription_drug.period = period
    prescription_drug.notes = notes
    prescription_drug.checked = checked
    prescription_drug.suspendedDate = suspendedDate
    prescription_drug.status = status
    prescription_drug.near = near
    prescription_drug.schedule = schedule
    prescription_drug.order_number = order_number

    session.add(prescription_drug)
    session_commit()

    return prescription_drug
