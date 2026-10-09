"""Service: infection control follow-up

The infectologist reviews the patients on antimicrobials: each running drug is
judged conforming or not (valid until a date), optionally watching for its
expiry or a posology change, and a next review date can be scheduled. The admission
status and its pending reasons are kept by the rule in
infection_control_status_service; this service records the reviews and serves
the follow-up data.
"""

from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
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
    InfectionControlPending,
    InfectionControlReview,
)
from models.main import User, db
from models.requests.infection_control_request import (
    InfectionControlBackfillRequest,
    InfectionControlListRequest,
    InfectionControlReviewRequest,
)
from repository.infection_control import infection_control_repository
from services import feature_service
from services.infection_control import infection_control_status_service as rule
from services.infection_control.antimicrobial_timeline_service import GAP_TOLERANCE
from utils import dateutils, status

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


def _check_feature():
    if not feature_service.has_feature(FeatureEnum.INFECTION_CONTROL):
        raise ValidationError(
            "Controle de infecção não está habilitado",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )


def _user_names(user_ids: set) -> dict:
    ids = [i for i in user_ids if i is not None]
    if not ids:
        return {}

    return {
        u.id: u.name
        for u in db.session.query(User.id, User.name).filter(User.id.in_(ids)).all()
    }


def _serialize_pending(pending: InfectionControlPending) -> dict:
    return {
        "id": str(pending.id),
        "type": pending.pending_type,
        "origin": pending.origin,
        "idDrug": pending.id_drug,
        "idPrescription": (
            str(pending.id_prescription) if pending.id_prescription else None
        ),
        "details": pending.details,
        "createdAt": dateutils.to_iso(pending.created_at),
    }


def _serialize_evaluation(evaluation: AntimicrobialEvaluation, names: dict) -> dict:
    return {
        "id": str(evaluation.id),
        "idReview": str(evaluation.id_review),
        "idDrug": evaluation.id_drug,
        "idPrescription": str(evaluation.id_prescription),
        "courseStart": dateutils.to_iso(evaluation.course_start),
        "conforming": evaluation.conforming,
        "notes": evaluation.notes,
        "posology": evaluation.posology,
        "validFrom": dateutils.to_iso(evaluation.valid_from),
        "validUntil": dateutils.to_iso(evaluation.valid_until),
        "triggers": evaluation.triggers or [],
        "status": evaluation.status,
        "closedAt": dateutils.to_iso(evaluation.closed_at),
        "closingType": evaluation.closing_type,
        "createdAt": dateutils.to_iso(evaluation.created_at),
        "createdBy": names.get(evaluation.created_by),
    }


def _get_state(admission_number: int, now: datetime) -> dict:
    """The follow-up of an admission: status, open reasons, reviews and the
    evaluations of each antimicrobial course.

    Courses are listed by drug and start, the same key the antimicrobial
    timeline uses, so the page can place each evaluation on its course.
    """
    admission = infection_control_repository.get_admission(
        admission_number=admission_number
    )
    reviews = infection_control_repository.get_reviews(
        admission_number=admission_number
    )
    evaluations = infection_control_repository.get_evaluations(
        admission_number=admission_number
    )
    pendings = infection_control_repository.get_open_pendings(
        admission_number=admission_number
    )
    names = _user_names(
        {r.created_by for r in reviews} | {e.created_by for e in evaluations}
    )

    admission_courses = rule.load_courses(admission_number=admission_number, now=now)
    courses = []
    for course in admission_courses.courses:
        history = [
            _serialize_evaluation(e, names)
            for e in reversed(evaluations)
            if rule.evaluation_matches_course(e, course)
        ]
        active = next(
            (
                e
                for e in history
                if e["status"] == AntimicrobialEvaluationStatusEnum.ACTIVE.value
            ),
            None,
        )
        courses.append(
            {
                "idDrug": rule.course_drug(course),
                "start": dateutils.to_iso(course.start),
                "ongoing": any(c is course for c in admission_courses.ongoing),
                "evaluation": active,
                "history": history,
            }
        )

    return {
        "enabled": True,
        "admissionNumber": admission_number,
        "followed": admission is not None,
        "status": admission.status if admission else None,
        "statusDate": dateutils.to_iso(admission.status_date) if admission else None,
        "nextReviewDate": (
            dateutils.to_iso(admission.next_review_date) if admission else None
        ),
        "recalculatedAt": (
            dateutils.to_iso(admission.recalculated_at) if admission else None
        ),
        "pendings": [_serialize_pending(p) for p in pendings],
        "reviews": [
            {
                "id": str(r.id),
                "notes": r.notes,
                "nextReviewDate": dateutils.to_iso(r.next_review_date),
                "createdAt": dateutils.to_iso(r.created_at),
                "createdBy": names.get(r.created_by),
            }
            for r in reviews
        ],
        "courses": courses,
    }


@has_permission(Permission.READ_PRESCRIPTION)
def get_admission_state(admission_number: int):
    """Infection control follow-up of an admission"""
    if not feature_service.has_feature(FeatureEnum.INFECTION_CONTROL):
        return {"enabled": False, "admissionNumber": admission_number}

    return _get_state(admission_number=admission_number, now=datetime.now())


def _validate_review(
    request_data: InfectionControlReviewRequest,
    admission_courses: rule.AdmissionCourses,
    now: datetime,
):
    if request_data.nextReviewDate is not None and request_data.nextReviewDate <= now:
        raise ValidationError(
            "A data da próxima revisão deve ser futura",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    drugs = [e.idDrug for e in request_data.evaluations]
    if len(drugs) != len(set(drugs)):
        raise ValidationError(
            "Antimicrobiano avaliado mais de uma vez",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    for evaluation in request_data.evaluations:
        course = admission_courses.ongoing_course(evaluation.idDrug)
        if course is None:
            raise ValidationError(
                "Antimicrobiano não está em uso neste atendimento",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

        if evaluation.validFrom is not None and (
            evaluation.validFrom > now or evaluation.validFrom < course.start
        ):
            raise ValidationError(
                "O início da avaliação deve estar entre o início do tratamento e agora",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

        # the validity may already be over (a retroactive record), but not
        # before the evaluation starts
        if evaluation.validUntil < (evaluation.validFrom or now):
            raise ValidationError(
                "A validade da avaliação deve ser posterior ao seu início",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

        if not set(evaluation.triggers) <= OPTIONAL_TRIGGERS:
            raise ValidationError(
                "Gatilho de pendência inválido",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )


@has_permission(Permission.WRITE_INFECTION_CONTROL)
def save_review(request_data: InfectionControlReviewRequest, user_context: User):
    """Record a review: evaluate running antimicrobials, schedule the next
    review and bring the admission status up to date"""
    _check_feature()

    now = datetime.now()
    admission_number = request_data.admissionNumber
    admission_courses = rule.load_courses(admission_number=admission_number, now=now)
    _validate_review(
        request_data=request_data, admission_courses=admission_courses, now=now
    )

    admission = infection_control_repository.lock_admission(
        admission_number=admission_number
    )
    # an admission is reviewed only once followed (by prescalc, the backfill or
    # started by hand)
    if admission is None:
        raise ValidationError(
            "Atendimento não está no acompanhamento do controle de infecção",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    review = InfectionControlReview()
    review.admission_number = admission_number
    review.notes = request_data.notes
    review.next_review_date = request_data.nextReviewDate
    review.created_at = now
    review.created_by = user_context.id
    db.session.add(review)
    db.session.flush()

    admission.id_last_review = review.id
    admission.next_review_date = request_data.nextReviewDate
    admission.updated_at = now
    admission.updated_by = user_context.id

    active_evaluations = infection_control_repository.get_active_evaluations(
        admission_number=admission_number
    )
    open_pendings = infection_control_repository.get_open_pendings(
        admission_number=admission_number
    )

    for evaluation_data in request_data.evaluations:
        course = admission_courses.ongoing_course(evaluation_data.idDrug)
        latest = course.items[-1]
        in_force = [
            previous
            for previous in active_evaluations
            if rule.evaluation_matches_course(previous, course)
        ]
        # a period over before the evaluation in force starts is a record of
        # the past, not a replacement
        retroactive = bool(in_force) and all(
            evaluation_data.validUntil < previous.valid_from for previous in in_force
        )

        evaluation = AntimicrobialEvaluation()
        evaluation.id_review = review.id
        evaluation.admission_number = admission_number
        evaluation.id_drug = evaluation_data.idDrug
        evaluation.id_prescription = latest.id_prescription
        evaluation.id_prescription_drug = latest.id_prescription_drug
        evaluation.course_start = course.start
        evaluation.conforming = evaluation_data.conforming
        evaluation.notes = evaluation_data.notes
        evaluation.posology = rule.posology_snapshot(course)
        evaluation.valid_from = evaluation_data.validFrom or now
        evaluation.valid_until = evaluation_data.validUntil
        evaluation.triggers = sorted(set(evaluation_data.triggers))
        evaluation.status = AntimicrobialEvaluationStatusEnum.ACTIVE.value
        evaluation.created_at = now
        evaluation.created_by = user_context.id
        if retroactive:
            evaluation.status = AntimicrobialEvaluationStatusEnum.CLOSED.value
            evaluation.closed_at = now
            evaluation.closing_type = (
                AntimicrobialEvaluationClosingEnum.RETROACTIVE.value
            )
        db.session.add(evaluation)
        db.session.flush()

        # the evaluation in force and its reasons stay as they are
        if retroactive:
            continue

        for previous in in_force:
            previous.status = AntimicrobialEvaluationStatusEnum.SUPERSEDED.value
            previous.closed_at = now
            previous.closing_type = AntimicrobialEvaluationClosingEnum.SUPERSEDED.value
            previous.id_superseded_by = evaluation.id
            previous.updated_at = now
            previous.updated_by = user_context.id

        for pending in open_pendings:
            if (
                pending.id_drug == evaluation_data.idDrug
                and pending.pending_type in EVALUATION_RESOLVED_TYPES
            ):
                rule.resolve_pending(
                    pending,
                    resolution=InfectionControlResolutionEnum.EVALUATED,
                    user_id=user_context.id,
                    now=now,
                    id_review=review.id,
                )

    for pending in open_pendings:
        if (
            pending.resolved_at is None
            and pending.pending_type in REVIEW_RESOLVED_TYPES
        ):
            rule.resolve_pending(
                pending,
                resolution=InfectionControlResolutionEnum.REVIEW_SAVED,
                user_id=user_context.id,
                now=now,
                id_review=review.id,
            )

    rule.apply_rule(
        admission=admission,
        admission_courses=admission_courses,
        origin=InfectionControlOriginEnum.REVIEW,
        user_id=user_context.id,
    )

    return _get_state(admission_number=admission_number, now=now)


@has_permission(Permission.WRITE_INFECTION_CONTROL)
def follow_admission(admission_number: int, user_context: User):
    """Start following an admission by hand, as prescalc does when it sees an
    antimicrobial: the record is created pending, with the reasons of its
    running drugs. An admission already followed just gets the rule applied."""
    _check_feature()

    now = datetime.now()
    if infection_control_repository.is_discharged(
        admission_number=admission_number, now=now
    ):
        raise ValidationError(
            "Paciente com alta não entra no acompanhamento",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    admission = rule.sync_admission(
        admission_number=admission_number,
        origin=InfectionControlOriginEnum.MANUAL,
        user_id=user_context.id,
        now=now,
    )
    if admission is None:
        raise ValidationError(
            "Nenhum antimicrobiano em uso neste atendimento",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    return _get_state(admission_number=admission_number, now=now)


@has_permission(Permission.READ_INFECTION_CONTROL)
def list_admissions(request_data: InfectionControlListRequest):
    """Followed admissions for the worklist, longest in their status first"""
    _check_feature()

    statuses = request_data.status or [
        InfectionControlStatusEnum.PENDING.value,
        InfectionControlStatusEnum.REVISED.value,
    ]
    rows = infection_control_repository.list_admissions(
        statuses=statuses, limit=request_data.limit, offset=request_data.offset
    )
    admission_numbers = [row.InfectionControlAdmission.admission_number for row in rows]

    pendings_by_admission: dict[int, list] = {}
    for pending in infection_control_repository.get_open_pendings_by_admission(
        admission_numbers=admission_numbers
    ):
        pendings_by_admission.setdefault(pending.admission_number, []).append(
            _serialize_pending(pending)
        )
    validity = infection_control_repository.get_earliest_validity_by_admission(
        admission_numbers=admission_numbers
    )
    last_prescriptions = infection_control_repository.get_last_prescriptions(
        admission_numbers=admission_numbers
    )

    admissions = []
    for row in rows:
        admission = row.InfectionControlAdmission
        patient = row.Patient
        last = last_prescriptions.get(admission.admission_number)
        admissions.append(
            {
                "admissionNumber": admission.admission_number,
                "idPatient": str(patient.idPatient) if patient else None,
                "birthdate": dateutils.to_iso(patient.birthdate) if patient else None,
                "gender": patient.gender if patient else None,
                "admissionDate": (
                    dateutils.to_iso(patient.admissionDate) if patient else None
                ),
                "bed": last.Prescription.bed if last else None,
                "department": last.department if last else None,
                "status": admission.status,
                "statusDate": dateutils.to_iso(admission.status_date),
                "nextReviewDate": dateutils.to_iso(admission.next_review_date),
                "earliestValidUntil": dateutils.to_iso(
                    validity.get(admission.admission_number)
                ),
                "pendings": pendings_by_admission.get(admission.admission_number, []),
            }
        )

    return {
        "count": infection_control_repository.count_admissions(statuses=statuses),
        "admissions": admissions,
    }


@has_permission(Permission.INTEGRATION_UTILS)
def backfill(request_data: InfectionControlBackfillRequest, user_context: User):
    """Follow the admissions already on antimicrobials when the feature is
    turned on (prescalc only sees new prescriptions).

    Runs one batch per call; call again with `after` = the returned `next`
    until it is None.
    """
    _check_feature()

    now = datetime.now()
    candidates = infection_control_repository.get_backfill_candidates(
        since=now - GAP_TOLERANCE, after=request_data.after, limit=request_data.limit
    )

    created = 0
    for admission_number in candidates:
        admission = rule.sync_admission(
            admission_number=admission_number,
            origin=InfectionControlOriginEnum.BACKFILL,
            user_id=user_context.id,
            now=now,
        )
        if admission is not None:
            created += 1

    return {
        "processed": len(candidates),
        "created": created,
        "next": (candidates[-1] if len(candidates) == request_data.limit else None),
    }
