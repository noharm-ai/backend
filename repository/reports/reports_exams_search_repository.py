from datetime import date, timedelta
from sqlalchemy import desc, asc

from models.main import db
from models.segment import Exams


def get_exams_by_patient(idPatient: int, days: int):
    return (
        db.session.query(Exams)
        .filter(Exams.idPatient == idPatient)
        .filter(Exams.date >= (date.today() - timedelta(days=days)))
        .order_by(asc(Exams.typeExam), desc(Exams.date))
        .all()
    )
