"""Repository: clinical notes related operations"""

from datetime import datetime, timedelta

from sqlalchemy import Integer, desc, func

from decorators.timed_decorator import timed
from models.main import User, db
from models.notes import ClinicalNotes
from services import cache_service, clinical_notes_service


def get_dialysis_cache(admission_number: int):
    """Get dialysis data to cache"""
    return (
        db.session.query(
            ClinicalNotes.id, ClinicalNotes.annotations, ClinicalNotes.date
        )
        .filter(ClinicalNotes.admissionNumber == admission_number)
        .filter(ClinicalNotes.dialysisText != "")
        .filter(ClinicalNotes.dialysisText != None)
        .filter(ClinicalNotes.date > func.current_date() - 3)
        .order_by(desc(ClinicalNotes.date))
        .all()
    )


def get_allergies_cache(admission_number: int):
    """Get allergies data to cache"""
    return (
        db.session.query(
            ClinicalNotes.id, ClinicalNotes.annotations, ClinicalNotes.date
        )
        .filter(ClinicalNotes.admissionNumber == admission_number)
        .filter(ClinicalNotes.allergyText != "")
        .filter(ClinicalNotes.allergyText != None)
        .filter(ClinicalNotes.date > func.current_date() - 120)
        .order_by(desc(ClinicalNotes.date))
        .all()
    )


@timed()
def get_signs(admission_number: int, user_context: User, cache=True):
    """Get signs data from db or cache"""
    signs = {}
    if cache:
        result = cache_service.get_by_key(
            f"""{user_context.schema}:{admission_number}:sinais"""
        )

        if result != None:
            result_list = result.get("lista", [])
            signs = {
                "id": str(result.get("fkevolucao", None)),
                "data": " ".join(result_list),
                "date": result.get("dtevolucao", None),
                "cache": True,
            }

        return signs

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
        signs = {
            "id": str(result[2]),
            "data": result[0],
            "date": result[1].isoformat(),
            "cache": False,
        }

    return signs


@timed()
def get_infos(admission_number, user_context: User, cache=True):
    """Get info data from db or cache"""
    infos = {}
    if cache:
        result = cache_service.get_by_key(
            f"""{user_context.schema}:{admission_number}:dados"""
        )

        if result != None:
            result_list = result.get("lista", [])
            infos = {
                "id": str(result.get("fkevolucao", None)),
                "data": " ".join(result_list),
                "date": result.get("dtevolucao", None),
                "cache": True,
            }

        return infos

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
        infos = {
            "id": str(result[2]),
            "data": result[0],
            "date": result[1].isoformat(),
            "cache": False,
        }

    return infos


@timed()
def get_allergies(
    admission_number, user_context: User, admission_date=None, cache=True
):
    """Get allergies data from db or cache"""
    allergies = []

    if cache:
        results = cache_service.get_range(
            key=f"""{user_context.schema}:{admission_number}:alergia""", days_ago=120
        )

        if results:
            texts = []
            for a in sorted(
                results,
                key=lambda d: d["dtevolucao"],
                reverse=True,
            ):
                text = " ".join(a.get("lista", []))
                if text in texts:
                    continue

                texts.append(text)
                allergies.append(
                    {
                        "id": str(a.get("fkevolucao", None)),
                        "text": text,
                        "date": a.get("dtevolucao", None),
                        "cache": True,
                        "source": "care",
                    }
                )

        return allergies

    cutoff_date = (
        datetime.today() - timedelta(days=120)
        if admission_date == None
        else admission_date
    ) - timedelta(days=1)

    results = (
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

    allergies = []
    for a in results:
        allergies.append(
            {
                "date": a[1].isoformat(),
                "text": a[0],
                "source": "care",
                "id": str(a[2]),
                "cache": False,
            }
        )
    return allergies


@timed()
def get_dialysis(admission_number: int, user_context: User, cache=True):
    """Get dialysis data from db or cache"""
    dialysis_data = []

    if cache:
        results = cache_service.get_range(
            key=f"""{user_context.schema}:{admission_number}:dialise""", days_ago=3
        )

        if results:
            texts = []
            for d in sorted(
                results,
                key=lambda d: d["dtevolucao"] if d["dtevolucao"] != None else "",
                reverse=True,
            ):
                text = " ".join(d.get("lista", []))
                if text in texts:
                    continue

                dialysis_data.append(
                    {
                        "id": str(d.get("fkevolucao", None)),
                        "text": " ".join(d.get("lista", [])),
                        "date": d.get("dtevolucao", None),
                        "cache": True,
                    }
                )

        return dialysis_data

    results = (
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

    for d in results:
        dialysis_data.append(
            {"date": d[1].isoformat(), "text": d[0], "id": str(d[3]), "cache": False}
        )

    return dialysis_data


@timed()
def get_admission_stats(admission_number: int, user_context: User, cache=True):
    """Get clinical notes stats by admission from db or cache"""
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
                stats_key = tag["name"] + "_count"
                if  stats_key in total_counts:
                    stats[tag["key"]] = total_counts[stats_key]
                else:
                    stats[tag["key"]] = 0

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
