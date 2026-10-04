"""Service: antimicrobial timeline of an admission

Turns every antimicrobial prescribed for an admission into treatment courses,
one per drug, so it is easy to tell when each one started, when it should end
and where it is now.

Hospitals prescribe in two ways and both end up as time spans:

* daily prescribers repeat the drug on each day's prescription, so each item
  covers about one day (from the prescription date to its expire date);
* CPOE hospitals keep a single order valid from its start to its expire date.

Spans of the same drug that overlap or follow each other are merged into one
course. A course survives a single missing day (a prescription that was not
issued); a longer break starts a new course.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import db
from models.prescription import Patient
from repository import antimicrobial_repository
from services import patient_service
from utils import dateutils, status

ONE_DAY = timedelta(days=1)
# breaks shorter than this are just prescription timing, not a gap in the treatment
CONTINUITY_SLACK = timedelta(hours=12)
# up to one whole day without the drug keeps the same course (plus timing slack)
GAP_TOLERANCE = timedelta(hours=36)

STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"
STATUS_FINISHED = "finished"


@dataclass
class TimelineItem:
    """One prescribed antimicrobial item, already resolved to a time span"""

    id_prescription: int
    id_prescription_drug: int
    id_drug: int
    drug: str
    substance: str | None
    atb_level: int | None
    cpoe: bool
    start: datetime
    # when the item was meant to stop: the prescription expire date (None for
    # an open-ended CPOE order)
    planned_end: datetime | None
    # when the item actually stopped (suspension), or will stop
    end: datetime
    suspended: bool
    dose: float | None
    measure_unit: str | None
    frequency: str | None
    route: str | None
    period_total: int | None


@dataclass
class Course:
    """Consecutive items of the same drug"""

    items: list[TimelineItem] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    end: datetime | None = None
    # the item that ends last decides how the course ended
    last_item: TimelineItem | None = None

    @property
    def start(self) -> datetime:
        """First day of the course"""
        return self.items[0].start


def build_item(row, now: datetime) -> TimelineItem:
    """Resolve a prescribed item to the span of time it covers"""
    start = row.date
    expire = row.expire if row.expire is None or row.expire >= start else start

    if expire is not None:
        planned_end = expire
    elif row.cpoe:
        # open-ended CPOE order: it is valid until someone suspends it
        planned_end = None
    else:
        planned_end = start + ONE_DAY

    end = planned_end if planned_end is not None else max(now, start)
    suspended = False
    if row.suspended_date is not None and row.suspended_date <= end:
        end = max(row.suspended_date, start)
        suspended = True

    return TimelineItem(
        id_prescription=row.id_prescription,
        id_prescription_drug=row.id_prescription_drug,
        id_drug=row.id_drug,
        drug=row.drug,
        substance=row.substance,
        atb_level=row.atb_level,
        cpoe=bool(row.cpoe),
        start=start,
        planned_end=planned_end,
        end=end,
        suspended=suspended,
        dose=row.dose,
        measure_unit=row.measure_unit,
        frequency=row.frequency,
        route=row.route,
        period_total=row.period_total,
    )


def group_courses(items: list[TimelineItem]) -> list[Course]:
    """Merge the items of each drug into courses, oldest course first"""
    by_drug: dict[int, list[TimelineItem]] = {}
    for item in items:
        by_drug.setdefault(item.id_drug, []).append(item)

    courses: list[Course] = []
    for drug_items in by_drug.values():
        current = None
        for item in sorted(drug_items, key=lambda i: (i.start, i.end)):
            if current is not None and item.start - current.end > GAP_TOLERANCE:
                current = None

            if current is None:
                current = Course()
                courses.append(current)
            elif item.start - current.end > CONTINUITY_SLACK:
                current.gaps.append({"start": current.end, "end": item.start})

            current.items.append(item)
            if current.end is None or item.end >= current.end:
                current.end = item.end
                current.last_item = item

    return sorted(courses, key=lambda c: (c.start, c.items[0].drug or ""))


def _days(start: datetime, end: datetime) -> int:
    """Started days between two dates (D1 is the first 24 hours)"""
    return max(1, math.ceil((end - start) / ONE_DAY))


def _planned_end(course: Course) -> datetime | None:
    """When the course is meant to end.

    CPOE orders carry it in the expire date of the latest order. Daily
    prescribers only know it when the integration sends the total period of
    the treatment (periodo_total), counted from the first day of the course.
    """
    latest = course.items[-1]
    if latest.cpoe and latest.planned_end is not None:
        return latest.planned_end

    period_total = next(
        (i.period_total for i in reversed(course.items) if i.period_total),
        None,
    )
    if period_total:
        return course.start + timedelta(days=period_total)

    return None


def _regimens(course: Course) -> list[dict]:
    """Consecutive items with the same dose, frequency and route, merged"""
    regimens = []
    for item in course.items:
        key = (item.dose, item.measure_unit, item.frequency, item.route)
        if regimens and regimens[-1]["key"] == key:
            regimens[-1]["end"] = max(regimens[-1]["end"], item.end)
            continue

        regimens.append({"key": key, "start": item.start, "end": item.end})

    return [
        {
            "start": dateutils.to_iso(r["start"]),
            "end": dateutils.to_iso(r["end"]),
            "dose": r["key"][0],
            "measureUnit": r["key"][1],
            "frequency": r["key"][2],
            "route": r["key"][3],
        }
        for r in regimens
    ]


def serialize_course(
    course: Course, now: datetime, discharge_date: datetime | None = None
) -> dict:
    """The course as the timeline shows it, judged at `now`"""
    end = course.end
    if discharge_date is not None and end > discharge_date:
        end = max(discharge_date, course.start)

    if end > now:
        course_status = STATUS_ACTIVE
    elif course.last_item.suspended and end == course.end:
        course_status = STATUS_SUSPENDED
    else:
        course_status = STATUS_FINISHED

    planned_end = _planned_end(course)
    latest = course.items[-1]

    return {
        "idDrug": latest.id_drug,
        "drug": latest.drug,
        "substance": latest.substance,
        "atbLevel": latest.atb_level,
        "cpoe": latest.cpoe,
        "status": course_status,
        "start": dateutils.to_iso(course.start),
        "end": dateutils.to_iso(end),
        "plannedEnd": dateutils.to_iso(planned_end),
        "plannedDays": (
            _days(course.start, planned_end) if planned_end is not None else None
        ),
        # started days of treatment up to now (or up to the end, when it is over)
        "days": _days(course.start, min(now, end)),
        "lastIdPrescription": str(latest.id_prescription),
        "prescriptionCount": len({i.id_prescription for i in course.items}),
        "regimens": _regimens(course),
        "gaps": [
            {"start": dateutils.to_iso(g["start"]), "end": dateutils.to_iso(g["end"])}
            for g in course.gaps
        ],
    }


def _get_patient_data(patient: Patient | None, last_prescription) -> dict:
    """Patient header of the timeline, filled from the latest prescription
    when the admission has no patient record"""
    prescription = last_prescription[0] if last_prescription else None
    weight = patient.weight if patient else None
    weight_date = patient.weightDate if patient else None
    height = patient.height if patient else None
    id_patient = patient.idPatient if patient else prescription.idPatient

    if weight is None:
        previous_weight = patient_service.get_patient_weight(id_patient)
        if previous_weight is not None:
            weight, weight_date, height = previous_weight

    return {
        "idPatient": str(id_patient),
        "admissionNumber": (
            patient.admissionNumber if patient else prescription.admissionNumber
        ),
        "admissionDate": dateutils.to_iso(patient.admissionDate if patient else None),
        "dischargeDate": dateutils.to_iso(patient.dischargeDate if patient else None),
        "dischargeReason": patient.dischargeReason if patient else None,
        "birthdate": dateutils.to_iso(patient.birthdate if patient else None),
        "gender": patient.gender if patient else None,
        "weight": weight,
        "weightDate": dateutils.to_iso(weight_date),
        "height": height,
        "idPrescription": str(prescription.id) if prescription else None,
        "bed": prescription.bed if prescription else None,
        "record": prescription.record if prescription else None,
        "department": last_prescription.department if last_prescription else None,
        "segment": last_prescription.segment if last_prescription else None,
    }


@has_permission(Permission.READ_PRESCRIPTION)
def get_timeline(admission_number: int):
    """Patient data and antimicrobial courses of an admission"""
    patient = (
        db.session.query(Patient)
        .filter(Patient.admissionNumber == admission_number)
        .first()
    )
    last_prescription = antimicrobial_repository.get_last_prescription(
        admission_number=admission_number
    )

    if patient is None and last_prescription is None:
        raise ValidationError(
            "Registro inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    now = datetime.now()
    items = [
        build_item(row, now=now)
        for row in antimicrobial_repository.get_admission_antimicrobials(
            admission_number=admission_number
        )
    ]
    discharge_date = patient.dischargeDate if patient else None

    return {
        "now": dateutils.to_iso(now),
        "patient": _get_patient_data(patient, last_prescription),
        "courses": [
            serialize_course(course, now=now, discharge_date=discharge_date)
            for course in group_courses(items)
        ],
    }
