"""Repository: patient related operations"""

from sqlalchemy import select, desc

from models.main import db
from models.prescription import Patient


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
