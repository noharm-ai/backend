from models.main import db
from sqlalchemy import desc, func, distinct
from sqlalchemy.orm import undefer

from models.appendix import *
from models.notes import ClinicalNotes
from models.prescription import *


def get_patients(
    id_segment,
    id_department_list,
    next_appointment_start_date,
    next_appointment_end_date,
    scheduled_by_list,
    attended_by_list,
    appointment=None,
):
    Pmax = db.aliased(Prescription)

    sq_appointment = (
        db.session.query(func.max(func.date(ClinicalNotes.date)))
        .select_from(ClinicalNotes)
        .filter(ClinicalNotes.admissionNumber == Prescription.admissionNumber)
        .filter(ClinicalNotes.position == "Agendamento")
        .label("appointment")
    )

    query = (
        db.session.query(Patient, Prescription, sq_appointment)
        .select_from(Patient)
        .join(
            Prescription,
            Prescription.id
            == db.session.query(func.max(Pmax.id))
            .select_from(Pmax)
            .filter(Pmax.idPatient == Patient.idPatient)
            .filter(Pmax.admissionNumber == Patient.admissionNumber)
            .filter(Pmax.idHospital == Patient.idHospital)
            .filter(Pmax.agg == True),
        )
        .order_by(desc("appointment"))
        .options(undefer(Patient.observation))
    )

    if id_segment:
        query = query.filter(Prescription.idSegment == id_segment)

    if id_department_list:
        query = query.filter(Prescription.idDepartment.in_(id_department_list))

    if next_appointment_start_date:
        query = query.filter(sq_appointment >= next_appointment_start_date)

    if next_appointment_end_date:
        query = query.filter(sq_appointment <= next_appointment_end_date)

    if appointment == "scheduled":
        query = query.filter(sq_appointment != None)

    if appointment == "not-scheduled":
        query = query.filter(sq_appointment == None)

    if scheduled_by_list:
        scheduled_by_query = (
            db.session.query(func.count())
            .select_from(ClinicalNotes)
            .filter(ClinicalNotes.admissionNumber == Prescription.admissionNumber)
            .filter(ClinicalNotes.position == "Agendamento")
            .filter(ClinicalNotes.user.in_(scheduled_by_list))
        )

        query = query.filter(scheduled_by_query.exists())

    if attended_by_list:
        attended_by_query = (
            db.session.query(func.count())
            .select_from(ClinicalNotes)
            .filter(ClinicalNotes.admissionNumber == Prescription.admissionNumber)
            .filter(ClinicalNotes.position != "Agendamento")
            .filter(ClinicalNotes.user.in_(attended_by_list))
        )

        query = query.filter(attended_by_query.exists())

    return query.limit(1500).all()


def get_patient_allergies(id_patient):
    return (
        db.session.query(
            Allergy.createdAt, func.coalesce(Substance.name, Allergy.drugName)
        )
        .distinct(func.coalesce(Substance.name, Allergy.drugName))
        .outerjoin(Drug, Allergy.idDrug == Drug.id)
        .outerjoin(Substance, Drug.sctid == Substance.id)
        .filter(Allergy.idPatient == id_patient)
        .filter(Allergy.active == True)
        .order_by(func.coalesce(Substance.name, Allergy.drugName))
        .limit(100)
        .all()
    )


def get_patient_weight(id_patient):
    return (
        db.session.query(Patient.weight, Patient.weightDate, Patient.height)
        .filter(Patient.idPatient == id_patient)
        .filter(Patient.weight != None)
        .filter(Patient.weightDate > func.now() - func.cast("1 month", INTERVAL))
        .order_by(desc(Patient.weightDate))
        .first()
    )
