from sqlalchemy import func, desc, Integer
from datetime import datetime, timedelta

from models.main import db, User
from models.notes import ClinicalNotes
from services import cache_service, clinical_notes_service


def get_signs(admission_number: int, user_context: User, cache=True):
    if cache:
        result = cache_service.get_by_key(
            f"""{user_context.schema}:{admission_number}:sinais"""
        )

        if result != None:
            result_list = result.get("lista", [])
            return {
                "id": str(result.get("fkevolucao", None)),
                "data": " ".join(result_list),
                "date": result.get("dtevolucao", None),
                "cache": True,
            }

    result = (
        db.session.query(ClinicalNotes.signsText, ClinicalNotes.date, ClinicalNotes.id)
        .select_from(ClinicalNotes)
        .filter(ClinicalNotes.admissionNumber == admission_number)
        .filter(ClinicalNotes.signsText != "")
        .filter(ClinicalNotes.signsText != None)
        .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=60)))
        .order_by(desc(ClinicalNotes.date))
        .first()
    )

    if result != None:
        return {
            "id": str(result[2]),
            "data": result[0],
            "date": result[1].isoformat(),
            "cache": False,
        }

    return {}


def get_infos(admission_number, user_context: User, cache=True):
    if cache:
        result = cache_service.get_by_key(
            f"""{user_context.schema}:{admission_number}:dados"""
        )

        if result != None:
            result_list = result.get("lista", [])
            return {
                "id": str(result.get("fkevolucao", None)),
                "data": " ".join(result_list),
                "date": result.get("dtevolucao", None),
                "cache": True,
            }

    result = (
        db.session.query(ClinicalNotes.infoText, ClinicalNotes.date, ClinicalNotes.id)
        .select_from(ClinicalNotes)
        .filter(ClinicalNotes.admissionNumber == admission_number)
        .filter(ClinicalNotes.infoText != "")
        .filter(ClinicalNotes.infoText != None)
        .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=60)))
        .order_by(desc(ClinicalNotes.date))
        .first()
    )

    if result != None:
        return {
            "id": str(result[2]),
            "data": result[0],
            "date": result[1].isoformat(),
            "cache": False,
        }

    return {}


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


def get_admission_stats(admission_number: int, user_context: User, cache=True):
    tags = clinical_notes_service.get_tags()
    stats = {}

    if cache:
        result = cache_service.get_range(
            key=f"""{user_context.schema}:{admission_number}:stats""", days_ago=6
        )

        total_counts = {}
        if result != None:
            for i in result:
                cache_stats = i.get("lista", [])

                for count_key, count_value in cache_stats.items():
                    total_counts[count_key] = (
                        total_counts.get(count_key, 0) + count_value
                    )

            for tag in tags:
                stats[tag["key"]] = total_counts[tag["name"] + "_count"]

        return stats

    q_stats = db.session.query().select_from(ClinicalNotes)

    for tag in tags:
        stats[tag["key"]] = 0

        q_stats = q_stats.add_columns(
            func.sum(
                func.cast(
                    func.coalesce(
                        ClinicalNotes.annotations[tag["name"] + "_count"].astext, "0"
                    ),
                    Integer,
                )
            ).label(tag["key"])
        )

    q_stats = (
        q_stats.filter(ClinicalNotes.admissionNumber == admission_number)
        .filter(ClinicalNotes.isExam == None)
        .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=6)))
    )

    stats_result = q_stats.first()

    if stats_result:
        for tag in tags:
            stats[tag["key"]] = getattr(stats_result, tag["key"])

    return stats
