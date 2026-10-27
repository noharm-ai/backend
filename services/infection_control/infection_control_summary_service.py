"""Service: infection control summary of an admission

What the infection control report reads of an admission, kept on its record
(ci_atendimento.resumo_acompanhamento): each antimicrobial course as the
timeline groups it, the department of each day and the culture facts. The
report (long-running-tasks) builds its files from it with SQL alone, so the
course grouping stays in this repository, and it survives the prescriptions
being archived.

The rule keeps it on every run (update_summary). The scheduled job runs every
hour, so the summary is written only when it changes, and a running course is
kept at day precision (coveredUntil). The cultures read DynamoDB, so the job
refreshes them once a day and when the admission closes (refresh_cultures).

Contract (v1), shared with InfectionControlReport in long-running-tasks:
{v, savedAt, status, courses: [{n, idDrug, idSubstance, cpoe, start, ongoing,
end, coveredUntil, plannedEnd, endedBy, treatmentDays, gaps, regimens,
idEvaluations}], days: [{date, idDepartment, idSegment}], culture: {checkedAt,
collected, positive, microorganisms, byCourse: {n: {collectedBefore,
collectedAt, resistantReleasedAt}}}}
"""

from datetime import date, datetime, time, timedelta

from models.enums import (
    CultureResultTypeEnum,
    FeatureEnum,
    InfectionControlStatusEnum,
)
from models.infection_control import InfectionControlAdmission
from repository import culture_repository, patient_repository
from repository.infection_control import infection_control_repository
from services import culture_service, feature_service
from services.infection_control.antimicrobial_timeline_service import (
    Course,
    course_regimens,
    planned_end_of,
    started_days,
)
from utils import dateutils

SUMMARY_VERSION = 1
# the cultures read DynamoDB: once a day is enough for the report
CULTURE_REFRESH = timedelta(hours=20)
# a culture collected in this window around the start of a course was
# collected for it (before the antimicrobial could change the result)
CULTURE_BEFORE_START = timedelta(hours=48)
CULTURE_AFTER_START = timedelta(hours=24)

ENDED = "ended"
ENDED_SUSPENDED = "suspended"
ENDED_DISCHARGE = "discharge"


def _parse(value) -> datetime | None:
    """A date stored as ISO text, as a datetime"""
    if value is None:
        return None

    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _as_datetime(value) -> datetime | None:
    """A date column read as a date or a datetime, as a datetime"""
    if value is None or isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime.combine(value, time.min)

    return None


def _course_until(course: dict, now: datetime) -> datetime:
    """The end of a summarized course, or now while it runs"""
    return _parse(course.get("end")) or now


def serialize_course(
    n: int,
    course: Course,
    ongoing: bool,
    evaluations: list,
    now: datetime,
    discharge_date: datetime | None = None,
) -> dict:
    """One course of the summary.

    A running course has no end yet: it says up to which day it ran
    (coveredUntil), so that it changes once a day, not on every run. A course
    that went past the discharge ends at the discharge, as the timeline shows.
    """
    # deferred to avoid a circular import: the rule imports this module
    from services.infection_control.infection_control_status_service import (
        evaluation_matches_course,
    )

    latest = course.items[-1]
    end = None
    ended_by = None
    if ongoing:
        covered = min(course.end, now)
    else:
        end = course.end
        ended_by = ENDED_SUSPENDED if course.last_item.suspended else ENDED
        if discharge_date is not None and end > discharge_date:
            end = max(discharge_date, course.start)
            ended_by = ENDED_DISCHARGE
        covered = end

    planned_end = planned_end_of(course)

    return {
        "n": n,
        "idDrug": latest.id_drug,
        "idSubstance": latest.id_substance,
        "cpoe": latest.cpoe,
        "start": dateutils.to_iso(course.start),
        "ongoing": ongoing,
        "end": dateutils.to_iso(end),
        "coveredUntil": covered.date().isoformat(),
        "plannedEnd": dateutils.to_iso(planned_end),
        "endedBy": ended_by,
        "treatmentDays": started_days(course.start, min(now, covered)),
        "gaps": [
            {"start": dateutils.to_iso(g["start"]), "end": dateutils.to_iso(g["end"])}
            for g in course.gaps
        ],
        # the posology as the timeline splits it; its end and notes are left
        # out, since they change every day
        "regimens": [
            {
                "start": regimen["start"],
                "dose": regimen["dose"],
                "measureUnit": regimen["measureUnit"],
                "frequency": regimen["frequency"],
                "route": regimen["route"],
            }
            for regimen in course_regimens(course)
        ],
        "idEvaluations": [
            e.id for e in evaluations if evaluation_matches_course(e, course)
        ],
    }


def summarize_days(admission_number: int, courses: list[dict]) -> list[dict]:
    """The department and segment of each day with an antimicrobial, from the
    prescription-days (the latest one of a day wins)"""
    if not courses:
        return []

    first = min(_parse(c["start"]) for c in courses)
    last = max(c["coveredUntil"] for c in courses)

    days = {}
    for row in infection_control_repository.get_prescription_days(
        admission_number=admission_number,
        since=datetime.combine(first.date(), time.min),
    ):
        day = row.date.date().isoformat()
        if day > last:
            break

        days[day] = {
            "date": day,
            "idDepartment": row.id_department,
            "idSegment": row.id_segment,
        }

    return list(days.values())


def build_summary(
    admission_number: int,
    admission_courses,
    status: InfectionControlStatusEnum,
    previous: dict | None = None,
) -> dict:
    """The summary of an admission from the courses the rule loaded. The
    culture facts are kept from the previous summary: only the job refreshes
    them (refresh_cultures)"""
    now = admission_courses.now
    evaluations = infection_control_repository.get_evaluations(
        admission_number=admission_number
    )

    discharge_date = None
    if admission_courses.discharged:
        patient = patient_repository.get_patient_by_admission(
            admission_number=admission_number
        )
        discharge_date = patient.dischargeDate if patient else None

    ongoing = {id(c) for c in admission_courses.ongoing}
    courses = [
        serialize_course(
            n=n,
            course=course,
            ongoing=id(course) in ongoing,
            evaluations=evaluations,
            now=now,
            discharge_date=discharge_date,
        )
        for n, course in enumerate(admission_courses.courses, start=1)
    ]

    summary = {
        "v": SUMMARY_VERSION,
        "savedAt": dateutils.to_iso(now),
        "status": status.value,
        "courses": courses,
        "days": summarize_days(admission_number=admission_number, courses=courses),
    }
    if previous and previous.get("culture") is not None:
        summary["culture"] = previous["culture"]

    return summary


def _comparable(summary: dict) -> dict:
    """The summary without what changes on every save"""
    return {k: v for k, v in summary.items() if k != "savedAt"}


def save_summary(admission: InfectionControlAdmission, summary: dict) -> bool:
    """Write the summary on the record when it changed; returns whether it did"""
    previous = admission.summary
    if previous is not None and _comparable(previous) == _comparable(summary):
        return False

    admission.summary = summary
    return True


def update_summary(
    admission: InfectionControlAdmission,
    admission_courses,
    status: InfectionControlStatusEnum,
) -> bool:
    """Bring the summary of a record up to date with the courses the rule
    loaded (called by apply_rule); returns whether it was written"""
    summary = build_summary(
        admission_number=admission.admission_number,
        admission_courses=admission_courses,
        status=status,
        previous=admission.summary,
    )

    return save_summary(admission=admission, summary=summary)


def _cultures_due(admission: InfectionControlAdmission, culture: dict, now) -> bool:
    """Whether the culture facts are older than CULTURE_REFRESH, or older
    than the close of the admission"""
    checked_at = _parse(culture.get("checkedAt"))
    if checked_at is None or now - checked_at >= CULTURE_REFRESH:
        return True

    return (
        admission.status == InfectionControlStatusEnum.CLOSED.value
        and checked_at < admission.status_date
    )


def _resistant_releases(
    drugs: list, id_substance: int | None, start: datetime, until: datetime
) -> set[str]:
    """Release dates of the resistant antibiograms of the course's substance
    released while it ran, read as the cultureResistant alert reads them
    (culture_service.get_culture_summary, keyed by substance)"""
    if id_substance is None:
        return set()

    releases = set()
    for drug in drugs:
        if drug.get("sctid") != id_substance:
            continue

        for item in drug.get("items") or []:
            if (
                item.get("result") is None
                or item.get("resultType") != CultureResultTypeEnum.RESISTANT.value
            ):
                continue

            released = _parse(item.get("releaseDate"))
            if released is not None and start <= released <= until:
                releases.add(dateutils.to_iso(released))

    return releases


def culture_facts(
    courses: list[dict], id_patient: int, schema: str, previous: dict, now: datetime
) -> dict:
    """What the report reads of the patient's cultures during the courses:
    the cultures collected (from 48 h before the first course until the last
    one ends) and the positive ones (an antibiogram names a microorganism),
    and for each course whether a culture was collected around its start and
    when a resistant result for its substance was released while it ran.

    The resistant releases add up across refreshes: the DynamoDB summary only
    keeps the latest antibiogram of each material, microorganism and drug.
    """
    since = min(_parse(c["start"]) for c in courses) - CULTURE_BEFORE_START
    until = max(_course_until(c, now) for c in courses)

    collected = culture_repository.get_cultures_collected(
        id_patient=id_patient, collected_since=since, collected_until=until
    )
    microorganisms = culture_repository.get_microorganisms(
        id_exam_items=[c.idExamItem for c in collected if c.idExamItem is not None]
    )
    positive = [c for c in collected if microorganisms.get(c.idExamItem)]

    drugs = []
    if feature_service.has_feature(FeatureEnum.CULTURE):
        drugs = culture_service.get_culture_summary(
            schema=schema, id_patient=id_patient
        )

    previous_by_course = previous.get("byCourse") or {}
    by_course = {}
    for course in courses:
        start = _parse(course["start"])
        around_start = [
            c
            for c in collected
            if c.collectionDate is not None
            and start - CULTURE_BEFORE_START
            <= _as_datetime(c.collectionDate)
            <= start + CULTURE_AFTER_START
        ]
        key = str(course["n"])
        resistant = set(
            (previous_by_course.get(key) or {}).get("resistantReleasedAt") or []
        ) | _resistant_releases(
            drugs=drugs,
            id_substance=course.get("idSubstance"),
            start=start,
            until=_course_until(course, now),
        )
        by_course[key] = {
            "collectedBefore": bool(around_start),
            "collectedAt": (
                dateutils.to_iso(_as_datetime(around_start[0].collectionDate))
                if around_start
                else None
            ),
            "resistantReleasedAt": sorted(resistant),
        }

    return {
        "collected": len(collected),
        "positive": len(positive),
        "microorganisms": sorted(
            {name for c in positive for name in microorganisms[c.idExamItem]}
        ),
        "byCourse": by_course,
    }


def refresh_cultures(
    admission: InfectionControlAdmission, schema: str, now: datetime | None = None
) -> bool:
    """Refresh the culture facts of the summary once CULTURE_REFRESH has
    passed or the admission closed (the scheduled job and the summary
    backfill, which know the schema the DynamoDB summary is keyed by);
    returns whether they were refreshed"""
    now = now or datetime.now()
    summary = admission.summary
    if not summary or not summary.get("courses"):
        return False

    culture = summary.get("culture") or {}
    if not _cultures_due(admission=admission, culture=culture, now=now):
        return False

    refreshed = {"checkedAt": dateutils.to_iso(now)}
    patient = patient_repository.get_patient_by_admission(
        admission_number=admission.admission_number
    )
    if patient is not None:
        refreshed.update(
            culture_facts(
                courses=summary["courses"],
                id_patient=patient.idPatient,
                schema=schema,
                previous=culture,
                now=now,
            )
        )

    admission.summary = {**summary, "culture": refreshed}
    return True
