from sqlalchemy import select, and_

from models.main import db, desc, User
from models.prescription import (
    Prescription,
    PrescriptionDrug,
    Drug,
    DrugAttributes,
    Frequency,
    MeasureUnit,
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

    query = (
        select(
            Prescription.id,
            Prescription.date,
            Prescription.expire,
            PrescriptionDrug.suspendedDate,
            PrescriptionDrug.id.label("idPrescriptionDrug"),
            PrescriptionDrug.dose,
            PrescriptionDrug.route,
            Drug.name,
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
        .outerjoin(Frequency, Frequency.id == PrescriptionDrug.idFrequency)
        .outerjoin(MeasureUnit, MeasureUnit.id == PrescriptionDrug.idMeasureUnit)
        .where(Prescription.admissionNumber == admission_number)
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
                "prescriptionDate": dateutils.to_iso(row.date),
                "prescriptionExpirationDate": dateutils.to_iso(row.expire),
                "suspensionDate": dateutils.to_iso(row.suspendedDate),
                "drug": row.name,
                "dose": row.dose,
                "measureUnit": row.measureUnit,
                "frequency": row.frequency,
                "route": row.route,
            }
        )

    return items
