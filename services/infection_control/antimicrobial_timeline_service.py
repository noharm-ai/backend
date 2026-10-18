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

from exception.validation_error import ValidationError
from models.enums import DrugAlertLevelEnum
from models.main import User
from models.prescription import Patient
from repository import patient_repository
from repository.infection_control import antimicrobial_repository
from services import patient_service, prescription_view_service
from utils import dateutils, prescriptionutils, status

ONE_DAY = timedelta(days=1)
# breaks shorter than this are just prescription timing, not a gap in the treatment
CONTINUITY_SLACK = timedelta(hours=12)
# up to one whole day without the drug keeps the same course (plus timing slack)
GAP_TOLERANCE = timedelta(hours=36)

STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"
STATUS_FINISHED = "finished"

# the screening alerts of a course are listed most severe first
ALERT_LEVEL_ORDER = {
    DrugAlertLevelEnum.HIGH.value: 0,
    DrugAlertLevelEnum.MEDIUM.value: 1,
    DrugAlertLevelEnum.LOW.value: 2,
}


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
    # dose in the drug's default unit and doses per day, to tell a posology
    # change apart from a different way of writing the same one
    doseconv: float | None = None
    daily_frequency: float | None = None
    # prescribed and default measure unit ids, for the dose per weight
    id_measure_unit: str | None = None
    default_measure_unit: str | None = None
    use_weight: bool = False
    # the observation written on the prescribed item (complemento)
    notes: str | None = None
    id_substance: int | None = None


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
        doseconv=row.doseconv,
        daily_frequency=row.daily_frequency,
        id_measure_unit=row.id_measure_unit,
        default_measure_unit=row.default_measure_unit,
        use_weight=bool(row.use_weight),
        notes=row.notes,
        id_substance=row.id_substance,
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


def _regimens(course: Course, weight: float | None = None) -> list[dict]:
    """Consecutive items with the same dose, frequency and route, merged.

    The notes are not part of the posology: daily prescribers rewrite them
    every day ("D3 de 7"), so a regimen shows the notes of its latest item.
    """
    regimens = []
    for item in course.items:
        key = (item.dose, item.measure_unit, item.frequency, item.route)
        if regimens and regimens[-1]["key"] == key:
            regimens[-1]["end"] = max(regimens[-1]["end"], item.end)
            regimens[-1]["latest"] = item
            continue

        regimens.append(
            {"key": key, "start": item.start, "end": item.end, "latest": item}
        )

    return [
        {
            "start": dateutils.to_iso(r["start"]),
            "end": dateutils.to_iso(r["end"]),
            "dose": r["key"][0],
            "measureUnit": r["key"][1],
            "frequency": r["key"][2],
            "route": r["key"][3],
            "notes": r["latest"].notes,
            **_dose_per_weight(r["latest"], weight),
        }
        for r in regimens
    ]


def _dose_per_weight(item: TimelineItem, weight: float | None) -> dict:
    """The dose per Kg and per Kg a day of an item, as the screening shows them"""
    dose_weight = prescriptionutils.get_dose_per_weight(
        dose=item.dose,
        weight=weight,
        frequency=item.daily_frequency,
        unit=item.id_measure_unit,
        default_unit=item.default_measure_unit,
        doseconv=item.doseconv,
        use_weight=item.use_weight,
        unit_label=item.measure_unit or item.id_measure_unit,
    )

    return {
        "doseWeight": dose_weight["doseWeight"],
        "doseWeightDay": dose_weight["doseWeightDay"],
    }


def serialize_course(
    course: Course,
    now: datetime,
    discharge_date: datetime | None = None,
    weight: float | None = None,
) -> dict:
    """The course as the timeline shows it, judged at `now`; the patient
    weight gives the dose per Kg of its regimens"""
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
        "regimens": _regimens(course, weight=weight),
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
        "idSegment": prescription.idSegment if prescription else None,
    }


def _get_screening_prescription(admission_number: int, last_prescription):
    """The prescription the exams and the alerts are read from: the one the
    screening shows for the patient now.

    That is the latest prescription-day (aggregated prescription), which holds
    every drug of the day, so an antimicrobial and a drug it interacts with
    meet even when they were prescribed apart. Without an aggregated
    prescription as recent as the latest real one (schemas that do not
    aggregate), the latest real prescription.
    """
    prescription = last_prescription[0] if last_prescription else None
    agg_prescription = antimicrobial_repository.get_last_agg_prescription(
        admission_number=admission_number
    )

    if agg_prescription is not None and (
        prescription is None or agg_prescription.date.date() >= prescription.date.date()
    ):
        return agg_prescription

    return prescription


def _get_exams(patient: Patient, prescription, user_context: User) -> dict:
    """The latest exams of the patient, read as the prescription view reads
    them for the screening prescription (the references come from its
    segment)"""
    if prescription is None:
        return {"exams": {}, "exams_card": [], "alerts": 0}

    return prescription_view_service.get_exams(
        prescription=prescription, patient=patient, user_context=user_context
    )


def _get_drug_alerts(
    patient: Patient, prescription, exam_data: dict, user_context: User
) -> dict:
    """The screening alerts of every drug of the screening prescription, keyed
    by idPrescriptionDrug (prescription_view_service.get_drug_alerts)"""
    if prescription is None:
        return {}

    return prescription_view_service.get_drug_alerts(
        prescription=prescription,
        patient=patient,
        segment=antimicrobial_repository.get_segment(id_segment=prescription.idSegment),
        exam_data=exam_data,
        user_context=user_context,
    )


def course_alerts(course: Course, drug_alerts: dict) -> dict:
    """The screening alerts of a course: those of its items in the screening
    prescription, so only a course prescribed there has any. An alert repeated
    by two items of the course (two prescriptions of the same day) is listed
    once. Most severe first."""
    alerts = []
    seen = set()
    id_substance = None

    for item in course.items:
        drug_alert = drug_alerts.get(str(item.id_prescription_drug))
        if drug_alert is None:
            continue

        id_substance = id_substance or drug_alert["idSubstance"]
        for alert in drug_alert["alerts"]:
            key = (alert["type"], alert["text"])
            if key in seen:
                continue

            seen.add(key)
            alerts.append(alert)

    alerts.sort(key=lambda a: ALERT_LEVEL_ORDER.get(a["level"], len(ALERT_LEVEL_ORDER)))

    return {"idSubstance": id_substance, "alerts": alerts}


def get_timeline(
    admission_number: int,
    courses: list[Course],
    now: datetime,
    user_context: User,
) -> dict:
    """Patient data, antimicrobial courses and latest exams of an admission,
    each current course with the alerts the screening raises for it.

    The courses come grouped by the caller, which judges them at `now` (the
    follow-up is built from the same ones). Carries no permission check: the
    caller has one.
    """
    patient = patient_repository.get_patient_by_admission(
        admission_number=admission_number
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

    discharge_date = patient.dischargeDate if patient else None
    patient_data = _get_patient_data(patient, last_prescription)

    screening_prescription = _get_screening_prescription(
        admission_number=admission_number, last_prescription=last_prescription
    )
    screening_patient = patient
    if screening_patient is None and screening_prescription is not None:
        # the view does the same for an admission with no patient record
        screening_patient = Patient()
        screening_patient.idPatient = screening_prescription.idPatient
        screening_patient.admissionNumber = screening_prescription.admissionNumber

    exam_data = _get_exams(
        screening_patient, screening_prescription, user_context=user_context
    )
    drug_alerts = _get_drug_alerts(
        screening_patient,
        screening_prescription,
        exam_data=exam_data,
        user_context=user_context,
    )

    return {
        "now": dateutils.to_iso(now),
        "patient": patient_data,
        "courses": [
            {
                **serialize_course(
                    course,
                    now=now,
                    discharge_date=discharge_date,
                    weight=patient_data["weight"],
                ),
                **course_alerts(course, drug_alerts=drug_alerts),
            }
            for course in courses
        ],
        # the prescription the screening shows for the patient now, which the
        # exams and the alerts are read from
        "screeningPrescription": (
            {
                "idPrescription": str(screening_prescription.id),
                "date": dateutils.to_iso(screening_prescription.date),
                "agg": bool(screening_prescription.agg),
            }
            if screening_prescription is not None
            else None
        ),
        # the exam card of the screening
        "exams": exam_data["exams_card"],
        "alertExams": exam_data["alerts"],
    }
