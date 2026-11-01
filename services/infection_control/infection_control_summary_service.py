"""Service: infection control summary of an admission

What the infection control report reads of an admission, kept on its record
(ci_atendimento.resumo_acompanhamento): each antimicrobial course as the
timeline groups it and the department of each day. The
report (long-running-tasks) builds its files from it with SQL alone, so the
course grouping stays in this repository, and it survives the prescriptions
being archived.

The rule keeps it on every run (update_summary). The scheduled job runs every
hour, so the summary is written only when it changes, and a running course is
kept at day precision (coveredUntil).

Contract (v1), shared with InfectionControlReport in long-running-tasks:
{v, savedAt, status, courses: [{n, idDrug, idSubstance, cpoe, start, ongoing,
end, coveredUntil, plannedEnd, endedBy, treatmentDays, gaps, regimens,
idEvaluations}], days: [{date, idDepartment, idSegment}]}. Summaries saved
before the report dropped its microbiology tab may still carry a culture key,
until they are next written; the report ignores it.
"""

from datetime import date, datetime, time

from models.enums import InfectionControlStatusEnum
from models.infection_control import InfectionControlAdmission
from repository import patient_repository
from repository.infection_control import infection_control_repository
from services.infection_control.antimicrobial_timeline_service import (
    Course,
    course_regimens,
    planned_end_of,
    started_days,
)
from utils import dateutils

SUMMARY_VERSION = 1

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
) -> dict:
    """The summary of an admission from the courses the rule loaded"""
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
    )

    return save_summary(admission=admission, summary=summary)
