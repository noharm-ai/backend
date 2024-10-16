from sqlalchemy import func, desc
from datetime import datetime, timedelta

from models.main import db
from models.notes import ClinicalNotes


def get_signs(admission_number):
    return (
        db.session.query(ClinicalNotes.signsText, ClinicalNotes.date)
        .select_from(ClinicalNotes)
        .filter(ClinicalNotes.admissionNumber == admission_number)
        .filter(ClinicalNotes.signsText != "")
        .filter(ClinicalNotes.signsText != None)
        .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=60)))
        .order_by(desc(ClinicalNotes.date))
        .first()
    )


def get_infos(admission_number):
    return (
        db.session.query(ClinicalNotes.infoText, ClinicalNotes.date)
        .select_from(ClinicalNotes)
        .filter(ClinicalNotes.admissionNumber == admission_number)
        .filter(ClinicalNotes.infoText != "")
        .filter(ClinicalNotes.infoText != None)
        .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=60)))
        .order_by(desc(ClinicalNotes.date))
        .first()
    )


def get_allergies(admission_number, admission_date=None):
    cutoff_date = (
        datetime.today() - timedelta(days=120)
        if admission_date == None
        else admission_date
    ) - timedelta(days=1)

    return (
        db.session.query(
            ClinicalNotes.allergyText,
            func.max(ClinicalNotes.date).label("maxdate"),
            func.max(ClinicalNotes.id),
        )
        .select_from(ClinicalNotes)
        .filter(ClinicalNotes.admissionNumber == admission_number)
        .filter(ClinicalNotes.allergyText != "")
        .filter(ClinicalNotes.allergyText != None)
        .filter(ClinicalNotes.date >= cutoff_date)
        .group_by(ClinicalNotes.allergyText)
        .order_by(desc("maxdate"))
        .limit(50)
        .all()
    )


def get_dialysis(admission_number):
    return (
        db.session.query(
            func.first_value(ClinicalNotes.dialysisText).over(
                partition_by=func.date(ClinicalNotes.date),
                order_by=desc(ClinicalNotes.date),
            ),
            func.first_value(ClinicalNotes.date).over(
                partition_by=func.date(ClinicalNotes.date),
                order_by=desc(ClinicalNotes.date),
            ),
            func.date(ClinicalNotes.date).label("date"),
            func.first_value(ClinicalNotes.id).over(
                partition_by=func.date(ClinicalNotes.date),
                order_by=desc(ClinicalNotes.date),
            ),
        )
        .distinct(func.date(ClinicalNotes.date))
        .filter(ClinicalNotes.admissionNumber == admission_number)
        .filter(ClinicalNotes.dialysisText != "")
        .filter(ClinicalNotes.dialysisText != None)
        .filter(ClinicalNotes.date > func.current_date() - 3)
        .order_by(desc("date"))
        .all()
    )
