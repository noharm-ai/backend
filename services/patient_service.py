from models.main import db
from sqlalchemy import desc, func

from models.appendix import *
from models.notes import ClinicalNotes
from models.prescription import *


def get_patients(id_segment, id_department_list, next_appointment_start_date, next_appointment_end_date):
    Pmax = db.aliased(Prescription)

    sq_last_appointment = db.session.query(func.max(ClinicalNotes.date))\
        .select_from(ClinicalNotes)\
        .filter(ClinicalNotes.admissionNumber == Prescription.admissionNumber)\
        .filter(ClinicalNotes.date <= func.current_date())\
        .label('last_appointment')

    sq_next_appointment = db.session.query(func.max(ClinicalNotes.date))\
        .select_from(ClinicalNotes)\
        .filter(ClinicalNotes.admissionNumber == Prescription.admissionNumber)\
        .filter(ClinicalNotes.date > func.current_date())\
        .label('next_appointment')

    query = db.session\
        .query(Patient, Prescription, sq_last_appointment, sq_next_appointment)\
        .select_from(Patient)\
        .join(\
            Prescription,\
            Prescription.id == db.session.query(func.max(Pmax.id))\
                .select_from(Pmax)\
                .filter(Pmax.idPatient == Patient.idPatient)\
                .filter(Pmax.admissionNumber == Patient.admissionNumber)\
                .filter(Pmax.idHospital == Patient.idHospital)\
                .filter(Pmax.agg == True)\
            )\
        .order_by(desc("next_appointment"))\

    if (id_segment):
        query = query.filter(Prescription.idSegment == id_segment)

    if (id_department_list):
        query = query.filter(Prescription.idDepartment.in_(id_department_list))

    if (next_appointment_start_date):
        query = query.filter(sq_next_appointment >= next_appointment_start_date)

    if (next_appointment_end_date):
        query = query.filter(sq_next_appointment <= next_appointment_end_date)

    return query.limit(500).all()