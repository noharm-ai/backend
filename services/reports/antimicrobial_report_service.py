from sqlalchemy import select, and_

from models.main import db, desc, User
from models.prescription import (
    Patient,
    Prescription,
    PrescriptionDrug,
    Drug,
    DrugAttributes,
    Frequency,
    MeasureUnit,
    Substance,
)
from exception.validation_error import ValidationError
from utils import dateutils, status


def get_history(admission_number: int, user: User):
    if admission_number == None:
        raise ValidationError(
            "admissionNUmber inválido",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    admission_list = [admission_number]
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
            .where(Patient.admissionNumber < admission_number)
            .order_by(desc(Patient.admissionDate))
            .limit(2)
        )

        a_list = db.session.execute(admissions_query).all()
        for a in a_list:
            admission_list.append(a.admissionNumber)

    query = (
        select(
            Prescription.id,
            Prescription.date,
            Prescription.expire,
            Prescription.admissionNumber,
            PrescriptionDrug.suspendedDate,
            PrescriptionDrug.id.label("idPrescriptionDrug"),
            PrescriptionDrug.dose,
            PrescriptionDrug.route,
            Drug.name,
            Substance.name.label("substance"),
            MeasureUnit.description.label("measureUnit"),
            Frequency.description.label("frequency"),
        )
        .select_from(Prescription)
        .join(PrescriptionDrug, PrescriptionDrug.idPrescription == Prescription.id)
        .join(Drug, Drug.id == PrescriptionDrug.idDrug)
        .join(
            DrugAttributes,
            and_(
                DrugAttributes.idDrug == PrescriptionDrug.idDrug,
                DrugAttributes.idSegment == PrescriptionDrug.idSegment,
            ),
        )
        .outerjoin(Substance, Drug.sctid == Substance.id)
        .outerjoin(Frequency, Frequency.id == PrescriptionDrug.idFrequency)
        .outerjoin(MeasureUnit, MeasureUnit.id == PrescriptionDrug.idMeasureUnit)
        .where(Prescription.admissionNumber.in_(admission_list))
        .where(DrugAttributes.antimicro == True)
        .order_by(desc(Prescription.date))
        .limit(2000)
    )

    results = db.session.execute(query).all()
    items = []

    for row in results:
        items.append(
            {
                "idPrescription": str(row.id),
                "idPrescriptionDrug": str(row.idPrescriptionDrug),
                "admissionNumber": row.admissionNumber,
                "prescriptionDate": dateutils.to_iso(row.date),
                "prescriptionExpirationDate": dateutils.to_iso(row.expire),
                "suspensionDate": dateutils.to_iso(row.suspendedDate),
                "drug": row.name,
                "substance": row.substance,
                "dose": row.dose,
                "measureUnit": row.measureUnit,
                "frequency": row.frequency,
                "route": row.route,
            }
        )

    return items
