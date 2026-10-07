"""Service: infection control status of an admission

The single rule that keeps an admission's infection control record
(ci_atendimento) and its pending reasons (ci_pendencia) in step with the
antimicrobials prescribed. The review save and the backfill go through it,
so it lives in one place (the scheduled job in backend-private follows the
same rule):

* an admission with a running antimicrobial course is followed; it is pending
  while it has an open reason and revised when none is left;
* a running course without an active evaluation opens a reason for its drug;
* an admission never reviewed opens a reason of its own;
* when a drug stops, its reasons are resolved and its evaluation is closed;
* with nothing running (or after discharge) the record is closed.

Prescalc runs many times a day, so it doesn't apply the rule: it only
follows the admissions that start (or restart) an antimicrobial, and the
scheduled job (backend-private) applies the rule to every followed admission.

The functions here carry no permission check: they run inside callers that
have one (the static context or a decorated endpoint).
"""

import json
from dataclasses import dataclass, field
from datetime import datetime

from models.enums import (
    AntimicrobialEvaluationClosingEnum,
    AntimicrobialEvaluationStatusEnum,
    FeatureEnum,
    InfectionControlOriginEnum,
    InfectionControlPendingTypeEnum,
    InfectionControlResolutionEnum,
    InfectionControlStatusEnum,
)
from models.infection_control import (
    AntimicrobialEvaluation,
    InfectionControlAdmission,
    InfectionControlPending,
)
from models.main import db
from models.prescription import Patient
from repository.infection_control import (
    antimicrobial_repository,
    infection_control_repository,
)
from services import feature_service
from services.infection_control.antimicrobial_timeline_service import (
    GAP_TOLERANCE,
    Course,
    build_item,
    group_courses,
)
from utils import dateutils, logger

# prescalc must not wait long for a writer holding the admission record
PRESCALC_LOCK_TIMEOUT_MS = 5000


@dataclass
class AdmissionCourses:
    """The antimicrobial courses of an admission, judged at `now`"""

    now: datetime
    courses: list[Course] = field(default_factory=list)
    # courses still running (or that may still continue, see is_ongoing)
    ongoing: list[Course] = field(default_factory=list)
    discharged: bool = False

    def ongoing_course(self, id_drug: int) -> Course | None:
        """The running course of a drug"""
        return next((c for c in self.ongoing if course_drug(c) == id_drug), None)


def course_drug(course: Course) -> int:
    """The drug of a course"""
    return course.items[0].id_drug


def is_ongoing(course: Course, now: datetime) -> bool:
    """Whether the course is running at `now`.

    A suspended course is over once suspended. Otherwise it is kept for the
    same tolerance the courses are grouped with: the next daily prescription
    may still arrive and continue it, and closing its evaluation in between
    would send the patient back to pending for nothing.
    """
    if course.last_item.suspended:
        return course.end > now

    return course.end + GAP_TOLERANCE > now


def evaluation_matches_course(
    evaluation: AntimicrobialEvaluation, course: Course
) -> bool:
    """Whether an evaluation was made for this course of the drug"""
    return (
        evaluation.id_drug == course_drug(course)
        and course.start <= evaluation.course_start <= course.end
    )


def posology_snapshot(course: Course) -> dict:
    """The posology of the latest item of a course, kept on its evaluation"""
    item = course.items[-1]
    return {
        "idPrescriptionDrug": str(item.id_prescription_drug),
        "dose": item.dose,
        "doseconv": item.doseconv,
        "measureUnit": item.measure_unit,
        "frequency": item.frequency,
        "dailyFrequency": item.daily_frequency,
        "route": item.route,
    }


def load_courses(admission_number: int, now: datetime) -> AdmissionCourses:
    """The antimicrobial courses of an admission and which of them are running"""
    items = [
        build_item(row, now=now)
        for row in antimicrobial_repository.get_admission_antimicrobials(
            admission_number=admission_number
        )
    ]
    courses = group_courses(items)

    discharge_date = (
        db.session.query(Patient.dischargeDate)
        .filter(Patient.admissionNumber == admission_number)
        .scalar()
    )
    discharged = discharge_date is not None and discharge_date <= now

    return AdmissionCourses(
        now=now,
        courses=courses,
        ongoing=[] if discharged else [c for c in courses if is_ongoing(c, now)],
        discharged=discharged,
    )


def resolve_pending(
    pending: InfectionControlPending,
    resolution: InfectionControlResolutionEnum,
    user_id: int,
    now: datetime,
    id_review: int | None = None,
):
    """Close a pending reason"""
    pending.resolved_at = now
    pending.resolution_type = resolution.value
    pending.resolved_by = user_id
    pending.id_review = id_review


def sync_admission(
    admission_number: int,
    origin: InfectionControlOriginEnum,
    user_id: int,
    now: datetime | None = None,
    id_prescription: int | None = None,
    lock_timeout_ms: int | None = None,
) -> InfectionControlAdmission | None:
    """Bring an admission's record up to date with its antimicrobials.

    The record is created (as pending) when the admission has a running
    course and is not followed yet. Returns the record, or None when the
    admission is not followed and has nothing running.
    """
    now = now or datetime.now()
    admission_courses = load_courses(admission_number=admission_number, now=now)

    admission = infection_control_repository.lock_admission(
        admission_number=admission_number, lock_timeout_ms=lock_timeout_ms
    )
    if admission is None:
        if not admission_courses.ongoing:
            return None

        infection_control_repository.create_admission(
            admission_number=admission_number,
            origin=origin.value,
            user_id=user_id,
            now=now,
        )
        admission = infection_control_repository.lock_admission(
            admission_number=admission_number, lock_timeout_ms=lock_timeout_ms
        )

    apply_rule(
        admission=admission,
        admission_courses=admission_courses,
        origin=origin,
        user_id=user_id,
        id_prescription=id_prescription,
    )

    return admission


def apply_rule(
    admission: InfectionControlAdmission,
    admission_courses: AdmissionCourses,
    origin: InfectionControlOriginEnum,
    user_id: int,
    id_prescription: int | None = None,
):
    """Open and resolve the pending reasons of a locked admission record and
    set its status from them"""
    now = admission_courses.now
    admission_number = admission.admission_number
    ongoing = admission_courses.ongoing

    # evaluations of courses that are over are no longer in force
    active_evaluations = []
    for evaluation in infection_control_repository.get_active_evaluations(
        admission_number=admission_number
    ):
        if any(evaluation_matches_course(evaluation, c) for c in ongoing):
            active_evaluations.append(evaluation)
            continue

        evaluation.status = AntimicrobialEvaluationStatusEnum.CLOSED.value
        evaluation.closed_at = now
        evaluation.closing_type = (
            AntimicrobialEvaluationClosingEnum.DISCHARGE.value
            if admission_courses.discharged
            else AntimicrobialEvaluationClosingEnum.COURSE_ENDED.value
        )
        evaluation.updated_at = now
        evaluation.updated_by = user_id

    if ongoing:
        if admission.id_last_review is None:
            infection_control_repository.open_pending(
                admission_number=admission_number,
                pending_type=InfectionControlPendingTypeEnum.NEVER_REVIEWED.value,
                origin=origin.value,
                user_id=user_id,
                now=now,
                id_prescription=id_prescription,
            )

        for course in ongoing:
            if any(evaluation_matches_course(e, course) for e in active_evaluations):
                continue

            latest = course.items[-1]
            infection_control_repository.open_pending(
                admission_number=admission_number,
                pending_type=InfectionControlPendingTypeEnum.NO_EVALUATION.value,
                origin=origin.value,
                user_id=user_id,
                now=now,
                id_drug=course_drug(course),
                id_prescription=id_prescription or latest.id_prescription,
                details={
                    "drug": latest.drug,
                    "courseStart": dateutils.to_iso(course.start),
                },
            )

    # reasons of drugs that stopped running are resolved
    ongoing_drugs = {course_drug(c) for c in ongoing}
    open_pendings = []
    for pending in infection_control_repository.get_open_pendings(
        admission_number=admission_number
    ):
        if not ongoing:
            resolve_pending(
                pending,
                resolution=(
                    InfectionControlResolutionEnum.DISCHARGE
                    if admission_courses.discharged
                    else InfectionControlResolutionEnum.DRUG_NO_LONGER_ACTIVE
                ),
                user_id=user_id,
                now=now,
            )
        elif pending.id_drug is not None and pending.id_drug not in ongoing_drugs:
            resolve_pending(
                pending,
                resolution=InfectionControlResolutionEnum.DRUG_NO_LONGER_ACTIVE,
                user_id=user_id,
                now=now,
            )
        else:
            open_pendings.append(pending)

    if not ongoing:
        status = InfectionControlStatusEnum.CLOSED
    elif open_pendings:
        status = InfectionControlStatusEnum.PENDING
    else:
        status = InfectionControlStatusEnum.REVISED

    if admission.status != status.value:
        admission.status = status.value
        admission.status_date = now
        admission.updated_at = now
        admission.updated_by = user_id

    admission.recalculated_at = now
    db.session.flush()


def follow_from_prescalc(
    schema: str,
    admission_number: int,
    features: dict,
    user_id: int,
    id_prescription: int | None = None,
):
    """Prescalc hook: follow an admission whose prescription-day has an
    antimicrobial.

    Only what can't wait for the job, and cheap enough for prescalc (no
    antimicrobial history, no wait for a record being reviewed):
    * an admission not followed yet gets its record, pending and never reviewed;
    * a closed record is reopened as pending (the antimicrobial restarted).

    A discharged patient is left alone.

    A followed record is left to the job, which also opens the reasons of each
    drug. Only for schemas with the INFECTION_CONTROL feature.

    Runs in a savepoint and never raises: the prescription-day is the core
    product and must be saved even if this step fails.
    """
    if not features or not features.get("am"):
        return

    # flush prescalc's own changes first: begin_nested() would flush them inside
    # the try below, and their errors must surface as prescalc errors
    db.session.flush()

    try:
        with (
            db.session.begin_nested(),
            infection_control_repository.lock_timeout(PRESCALC_LOCK_TIMEOUT_MS),
        ):
            if not feature_service.has_feature(FeatureEnum.INFECTION_CONTROL):
                return

            now = datetime.now()
            # a discharged patient's prescriptions are still recalculated
            # (e.g. drugs suspended at discharge): they start nothing
            if infection_control_repository.is_discharged(
                admission_number=admission_number, now=now
            ):
                return

            created = infection_control_repository.create_admission(
                admission_number=admission_number,
                origin=InfectionControlOriginEnum.PRESCALC.value,
                user_id=user_id,
                now=now,
            )
            reopened = (
                None
                if created
                else infection_control_repository.reopen_admission(
                    admission_number=admission_number, user_id=user_id, now=now
                )
            )

            # reopened after a review: the job opens the reasons of its drugs
            if created or (reopened and reopened.id_last_review is None):
                infection_control_repository.open_pending(
                    admission_number=admission_number,
                    pending_type=InfectionControlPendingTypeEnum.NEVER_REVIEWED.value,
                    origin=InfectionControlOriginEnum.PRESCALC.value,
                    user_id=user_id,
                    now=now,
                    id_prescription=id_prescription,
                )
    except Exception as e:  # noqa: BLE001 - must not break the prescription-day
        # same event as the static context's errors, which is the one monitored
        logger.backend_logger.error(
            json.dumps(
                {
                    "event": "backend_exception",
                    "path": "infection_control_status_service.follow_from_prescalc",
                    "schema": schema,
                    "message": str(e),
                    "admission_number": admission_number,
                }
            )
        )
