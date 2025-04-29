"""Repository: exams related operations"""

from datetime import date, timedelta
from sqlalchemy import desc, asc, func

from models.main import db
from models.segment import Exams, SegmentExam


def get_exams_by_patient(idPatient: int, days: int):
    """Get exams by patient"""
    return (
        db.session.query(Exams)
        .filter(Exams.idPatient == idPatient)
        .filter(Exams.date >= (date.today() - timedelta(days=days)))
        .order_by(asc(Exams.typeExam), desc(Exams.date))
        .all()
    )


def get_next_exam_id(id_patient: int):
    """Generate a 12-digit exam ID with format: 9{id_patient}00000000"""

    patient_str = str(id_patient)
    if len(patient_str) > 10:
        raise ValueError("id_patient must be 8 digits or less")

    exam_id = "9" + patient_str + "0" * (12 - len(patient_str))
    mask = int(exam_id)

    count = (
        db.session.query(Exams)
        .filter(Exams.idPatient == id_patient)
        .filter(Exams.idExame >= mask)
        .count()
    )
    return mask + count + 1


def get_exam_types():
    """Get all exam types"""
    return (
        db.session.query(SegmentExam.typeExam, func.max(SegmentExam.name).label("name"))
        .filter(SegmentExam.active == True)
        .group_by(SegmentExam.typeExam)
        .order_by("name")
        .all()
    )
