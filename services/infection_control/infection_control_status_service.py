"""Service: infection control status of an admission

The single rule that keeps an admission's infection control record
(ci_atendimento) and its pending reasons (ci_pendencia) in step with the
antimicrobials prescribed. The review save, the manual follow and the
backfill go through it, so it lives in one place (the scheduled job in
backend-private follows the same rule). plan_rule decides, apply_rule writes
the plan; a saved review also records its evaluations here
(record_evaluation, resolve_on_review):

* an admission with a running antimicrobial course is followed; it is pending
  while it has an open reason and revised when none is left;
* a running course without an active evaluation opens a reason for its drug;
* a running course whose evaluation expired, or whose posology changed from
  the evaluated one, opens a reason when its evaluation opted into that
  trigger;
* an admission never reviewed opens a reason of its own, and so does one
  whose scheduled review date arrived;
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
    InfectionControlReview,
)
from models.main import db
from models.prescription import Patient
from models.requests.infection_control_request import AntimicrobialEvaluationRequest
from repository.infection_control import (
    antimicrobial_repository,
    infection_control_repository,
)
from services import feature_service
from services.infection_control.antimicrobial_timeline_service import (
    GAP_TOLERANCE,
    Course,
    TimelineItem,
    build_item,
    group_courses,
)
from utils import dateutils, logger

# prescalc must not wait long for a writer holding the admission record
PRESCALC_LOCK_TIMEOUT_MS = 5000

# reasons a saved review settles by itself, whatever drugs it evaluates
REVIEW_RESOLVED_TYPES = [
    InfectionControlPendingTypeEnum.NEVER_REVIEWED.value,
    InfectionControlPendingTypeEnum.SCHEDULED_DATE.value,
]
# reasons of one drug that its new evaluation settles
EVALUATION_RESOLVED_TYPES = [
    InfectionControlPendingTypeEnum.NO_EVALUATION.value,
    InfectionControlPendingTypeEnum.EXPIRED.value,
    InfectionControlPendingTypeEnum.POSOLOGY_CHANGED.value,
]
# reasons an evaluation may opt into (the others always apply)
OPTIONAL_TRIGGERS = {
    InfectionControlPendingTypeEnum.EXPIRED.value,
    InfectionControlPendingTypeEnum.POSOLOGY_CHANGED.value,
}


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


@dataclass
class RulePlan:
    """Changes the rule makes to one admission record"""

    close_evaluations: list[int] = field(default_factory=list)
    closing_type: AntimicrobialEvaluationClosingEnum | None = None
    open_pendings: list[dict] = field(default_factory=list)
    resolve_pendings: dict[InfectionControlResolutionEnum, list[int]] = field(
        default_factory=dict
    )
    status: InfectionControlStatusEnum = InfectionControlStatusEnum.CLOSED


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


def item_posology(item: TimelineItem) -> dict:
    """The posology of a prescribed item"""
    return {
        "idPrescriptionDrug": str(item.id_prescription_drug),
        "dose": item.dose,
        "doseconv": item.doseconv,
        "measureUnit": item.measure_unit,
        "frequency": item.frequency,
        "dailyFrequency": item.daily_frequency,
        "route": item.route,
    }


def posology_snapshot(course: Course) -> dict:
    """The posology of the latest item of a course, kept on its evaluation"""
    return item_posology(course.items[-1])


def _same_number(a, b) -> bool:
    return round(float(a), 4) == round(float(b), 4)


def _same_text(a, b) -> bool:
    return (a or "").strip().upper() == (b or "").strip().upper()


def same_posology(evaluated: dict, current: dict) -> bool:
    """Whether two posologies are the same treatment.

    Dose and frequency are compared converted (default unit, doses per day)
    when both sides have it, so writing the same posology another way is not
    a change; otherwise as written.
    """
    if evaluated.get("doseconv") is not None and current.get("doseconv") is not None:
        same_dose = _same_number(evaluated["doseconv"], current["doseconv"])
    elif evaluated.get("dose") is not None and current.get("dose") is not None:
        same_dose = _same_number(evaluated["dose"], current["dose"]) and _same_text(
            evaluated.get("measureUnit"), current.get("measureUnit")
        )
    else:
        same_dose = evaluated.get("dose") is None and current.get("dose") is None

    if (
        evaluated.get("dailyFrequency") is not None
        and current.get("dailyFrequency") is not None
    ):
        same_frequency = _same_number(
            evaluated["dailyFrequency"], current["dailyFrequency"]
        )
    else:
        same_frequency = _same_text(
            evaluated.get("frequency"), current.get("frequency")
        )

    return (
        same_dose
        and same_frequency
        and _same_text(evaluated.get("route"), current.get("route"))
    )


def posology_changed(evaluation: AntimicrobialEvaluation, course: Course) -> bool:
    """Whether the course is no longer prescribed as its evaluation judged it.

    Only the latest prescription counts, and any of its items of the drug
    matching is enough: a drug written in two lines (e.g. a loading dose)
    must not flip between changed and unchanged.
    """
    latest = course.items[-1].id_prescription
    return not any(
        same_posology(evaluation.posology, item_posology(item))
        for item in course.items
        if item.id_prescription == latest
    )


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


def record_evaluation(
    review: InfectionControlReview,
    course: Course,
    evaluation_data: AntimicrobialEvaluationRequest,
    active_evaluations: list[AntimicrobialEvaluation],
    open_pendings: list[InfectionControlPending],
    user_id: int,
    now: datetime,
) -> AntimicrobialEvaluation:
    """Record the evaluation of a running course made in a review.

    The new evaluation replaces the one in force and resolves the reasons of
    its drug. When it only covers a period over before the evaluation in force
    started, it is a record of the past: it goes straight to the history and
    leaves that evaluation and its reasons as they are.
    """
    latest = course.items[-1]
    in_force = [
        previous
        for previous in active_evaluations
        if evaluation_matches_course(previous, course)
    ]
    retroactive = bool(in_force) and all(
        evaluation_data.validUntil < previous.valid_from for previous in in_force
    )

    evaluation = AntimicrobialEvaluation()
    evaluation.id_review = review.id
    evaluation.admission_number = review.admission_number
    evaluation.id_drug = evaluation_data.idDrug
    evaluation.id_prescription = latest.id_prescription
    evaluation.id_prescription_drug = latest.id_prescription_drug
    evaluation.course_start = course.start
    evaluation.conforming = evaluation_data.conforming
    evaluation.notes = evaluation_data.notes
    evaluation.posology = posology_snapshot(course)
    evaluation.valid_from = evaluation_data.validFrom or now
    evaluation.valid_until = evaluation_data.validUntil
    evaluation.triggers = sorted(set(evaluation_data.triggers))
    evaluation.status = AntimicrobialEvaluationStatusEnum.ACTIVE.value
    evaluation.created_at = now
    evaluation.created_by = user_id
    if retroactive:
        evaluation.status = AntimicrobialEvaluationStatusEnum.CLOSED.value
        evaluation.closed_at = now
        evaluation.closing_type = AntimicrobialEvaluationClosingEnum.RETROACTIVE.value
    db.session.add(evaluation)
    db.session.flush()

    if retroactive:
        return evaluation

    for previous in in_force:
        previous.status = AntimicrobialEvaluationStatusEnum.SUPERSEDED.value
        previous.closed_at = now
        previous.closing_type = AntimicrobialEvaluationClosingEnum.SUPERSEDED.value
        previous.id_superseded_by = evaluation.id
        previous.updated_at = now
        previous.updated_by = user_id

    for pending in open_pendings:
        if (
            pending.id_drug == evaluation.id_drug
            and pending.pending_type in EVALUATION_RESOLVED_TYPES
        ):
            resolve_pending(
                pending,
                resolution=InfectionControlResolutionEnum.EVALUATED,
                user_id=user_id,
                now=now,
                id_review=review.id,
            )

    return evaluation


def resolve_on_review(
    review: InfectionControlReview,
    open_pendings: list[InfectionControlPending],
    user_id: int,
    now: datetime,
):
    """Resolve the reasons any saved review settles (never reviewed, scheduled
    date), whatever drugs it evaluates"""
    for pending in open_pendings:
        if (
            pending.resolved_at is None
            and pending.pending_type in REVIEW_RESOLVED_TYPES
        ):
            resolve_pending(
                pending,
                resolution=InfectionControlResolutionEnum.REVIEW_SAVED,
                user_id=user_id,
                now=now,
                id_review=review.id,
            )


def sync_admission(
    admission_number: int,
    origin: InfectionControlOriginEnum,
    user_id: int,
    now: datetime | None = None,
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
    )

    return admission


def course_reasons(
    course: Course, evaluation: AntimicrobialEvaluation | None, now: datetime
) -> list[tuple[InfectionControlPendingTypeEnum, dict]]:
    """The reasons a running course gives, with their details, judged by its
    active evaluation"""
    if evaluation is None:
        return [
            (
                InfectionControlPendingTypeEnum.NO_EVALUATION,
                {"courseStart": dateutils.to_iso(course.start)},
            )
        ]

    triggers = evaluation.triggers or []
    reasons = []
    if (
        InfectionControlPendingTypeEnum.EXPIRED.value in triggers
        and evaluation.valid_until <= now
    ):
        reasons.append(
            (
                InfectionControlPendingTypeEnum.EXPIRED,
                {"validUntil": dateutils.to_iso(evaluation.valid_until)},
            )
        )

    if (
        InfectionControlPendingTypeEnum.POSOLOGY_CHANGED.value in triggers
        and posology_changed(evaluation, course)
    ):
        reasons.append(
            (
                InfectionControlPendingTypeEnum.POSOLOGY_CHANGED,
                {
                    "evaluated": evaluation.posology,
                    "current": posology_snapshot(course),
                },
            )
        )

    return reasons


def plan_rule(
    ongoing: list[Course],
    discharged: bool,
    id_last_review: int | None,
    active_evaluations: list[AntimicrobialEvaluation],
    open_pendings: list[InfectionControlPending],
    now: datetime,
    next_review_date: datetime | None = None,
) -> RulePlan:
    """Decide which evaluations close, which reasons open or resolve and the
    resulting status, without touching the database"""
    plan = RulePlan()

    # evaluations of courses that are over are no longer in force
    kept_evaluations = []
    for evaluation in active_evaluations:
        if any(evaluation_matches_course(evaluation, c) for c in ongoing):
            kept_evaluations.append(evaluation)
        else:
            plan.close_evaluations.append(evaluation.id)

    if plan.close_evaluations:
        plan.closing_type = (
            AntimicrobialEvaluationClosingEnum.DISCHARGE
            if discharged
            else AntimicrobialEvaluationClosingEnum.COURSE_ENDED
        )

    if ongoing:
        if id_last_review is None:
            plan.open_pendings.append(
                {"pending_type": InfectionControlPendingTypeEnum.NEVER_REVIEWED}
            )

        if next_review_date is not None and next_review_date <= now:
            plan.open_pendings.append(
                {
                    "pending_type": InfectionControlPendingTypeEnum.SCHEDULED_DATE,
                    "details": {"nextReviewDate": dateutils.to_iso(next_review_date)},
                }
            )

        for course in ongoing:
            latest = course.items[-1]
            evaluation = next(
                (e for e in kept_evaluations if evaluation_matches_course(e, course)),
                None,
            )
            for pending_type, details in course_reasons(course, evaluation, now):
                plan.open_pendings.append(
                    {
                        "pending_type": pending_type,
                        "id_drug": course_drug(course),
                        "id_prescription": latest.id_prescription,
                        "id_evaluation": evaluation.id if evaluation else None,
                        "details": {"drug": latest.drug, **details},
                    }
                )

    # reasons of drugs that stopped running are resolved
    ongoing_drugs = {course_drug(c) for c in ongoing}
    still_open = 0
    for pending in open_pendings:
        if not ongoing:
            resolution = (
                InfectionControlResolutionEnum.DISCHARGE
                if discharged
                else InfectionControlResolutionEnum.DRUG_NO_LONGER_ACTIVE
            )
        elif (
            pending.id_drug is not None and pending.id_drug not in ongoing_drugs
        ) or pending.id_evaluation in plan.close_evaluations:
            # a drug restarted in a new course: the old evaluation's reasons go
            resolution = InfectionControlResolutionEnum.DRUG_NO_LONGER_ACTIVE
        else:
            still_open += 1
            continue

        plan.resolve_pendings.setdefault(resolution, []).append(pending.id)

    # reasons opened now are always for running drugs, so they stay open
    if not ongoing:
        plan.status = InfectionControlStatusEnum.CLOSED
    elif still_open or plan.open_pendings:
        plan.status = InfectionControlStatusEnum.PENDING
    else:
        plan.status = InfectionControlStatusEnum.REVISED

    return plan


def apply_rule(
    admission: InfectionControlAdmission,
    admission_courses: AdmissionCourses,
    origin: InfectionControlOriginEnum,
    user_id: int,
):
    """Plan the rule for a locked admission record and write the plan: close
    evaluations, open and resolve pending reasons and set the status"""
    now = admission_courses.now
    admission_number = admission.admission_number
    active_evaluations = infection_control_repository.get_active_evaluations(
        admission_number=admission_number
    )
    open_pendings = infection_control_repository.get_open_pendings(
        admission_number=admission_number
    )

    plan = plan_rule(
        ongoing=admission_courses.ongoing,
        discharged=admission_courses.discharged,
        id_last_review=admission.id_last_review,
        active_evaluations=active_evaluations,
        open_pendings=open_pendings,
        now=now,
        next_review_date=admission.next_review_date,
    )

    evaluations_by_id = {e.id: e for e in active_evaluations}
    for id_evaluation in plan.close_evaluations:
        evaluation = evaluations_by_id[id_evaluation]
        evaluation.status = AntimicrobialEvaluationStatusEnum.CLOSED.value
        evaluation.closed_at = now
        evaluation.closing_type = plan.closing_type.value
        evaluation.updated_at = now
        evaluation.updated_by = user_id

    for pending in plan.open_pendings:
        infection_control_repository.open_pending(
            admission_number=admission_number,
            pending_type=pending["pending_type"].value,
            origin=origin.value,
            user_id=user_id,
            now=now,
            id_drug=pending.get("id_drug"),
            id_prescription=pending.get("id_prescription"),
            id_evaluation=pending.get("id_evaluation"),
            details=pending.get("details"),
        )

    pendings_by_id = {p.id: p for p in open_pendings}
    for resolution, id_pending_list in plan.resolve_pendings.items():
        for id_pending in id_pending_list:
            resolve_pending(
                pendings_by_id[id_pending],
                resolution=resolution,
                user_id=user_id,
                now=now,
            )

    if admission.status != plan.status.value:
        admission.status = plan.status.value
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
