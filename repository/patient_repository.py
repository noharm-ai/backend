"""Repository: patient related operations"""

from sqlalchemy import desc, select

from models.enums import PatientAuditTypeEnum
from models.main import User, db
from models.prescription import Patient, PatientAudit


def get_latest_admissions_by_id_patient(id_patient: int, limit: int = 2):
    """
    Search for latest admission number by id_patient
    """
    admission_list = []
    admissions_query = (
        select(Patient.admissionNumber)
        .select_from(Patient)
        .where(Patient.idPatient == id_patient)
        .order_by(desc(Patient.admissionDate))
        .limit(limit)
    )

    result = db.session.execute(admissions_query).all()

    for a in result:
        admission_list.append(int(a.admissionNumber))

    return admission_list


def get_next_admissions(admission_number: int, limit: int = 2):
    """
    Search for next admission numbers
    """
    admission_list = []
    admission = db.session.execute(
        select(Patient.idPatient)
        .select_from(Patient)
        .where(Patient.admissionNumber == admission_number)
    ).first()

    if admission != None:
        admissions_query = (
            select(Patient.admissionNumber)
            .select_from(Patient)
            .where(Patient.idPatient == admission.idPatient)
            .where(Patient.admissionNumber > admission_number)
            .order_by(desc(Patient.admissionDate))
            .limit(limit)
        )

        a_list = db.session.execute(admissions_query).all()
        for a in a_list:
            admission_list.append(int(a.admissionNumber))

    return admission_list


def get_previous_admissions(id_patient: int, admission_number: int, limit: int = 2):
    """
    Search for previous admission numbers
    """
    admission_list = [admission_number]

    admissions_query = (
        select(Patient.admissionNumber)
        .select_from(Patient)
        .where(Patient.idPatient == id_patient)
        .where(Patient.admissionNumber < admission_number)
        .order_by(desc(Patient.admissionDate))
        .limit(limit)
    )

    a_list = db.session.execute(admissions_query).all()
    for a in a_list:
        admission_list.append(int(a.admissionNumber))

    return admission_list


def get_patient_observation_history(admission_number: int):
    """Get patient observation history"""

    query = (
        select(PatientAudit.id, PatientAudit.extra, PatientAudit.createdAt, User.name)
        .select_from(PatientAudit)
        .outerjoin(User, PatientAudit.createdBy == User.id)
        .where(PatientAudit.admissionNumber == admission_number)
        .where(PatientAudit.auditType == PatientAuditTypeEnum.OBSERVATION_RECORD.value)
        .order_by(desc(PatientAudit.createdAt))
    )

    return db.session.execute(query).all()
