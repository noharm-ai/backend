"""Service: infection control follow-up

The infectologist reviews the patients on antimicrobials: each running drug is
judged conforming or not (valid until a date), optionally watching for its
expiry or a posology change, and a next review date can be scheduled. The admission
status and its pending reasons are kept by the rule in
infection_control_status_service; this service records the reviews and serves
the follow-up data.
"""

import json
from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.enums import (
    AntimicrobialEvaluationClosingEnum,
    AntimicrobialEvaluationStatusEnum,
    FeatureEnum,
    InfectionControlOriginEnum,
    InfectionControlStatusEnum,
    InterventionReasonRelationTypeEnum,
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
from repository import user_repository
from repository.infection_control import infection_control_repository
from services import feature_service, intervention_service
from services.infection_control import (
    antimicrobial_timeline_service,
    infection_control_status_service as rule,
)
from services.infection_control.antimicrobial_timeline_service import GAP_TOLERANCE
from utils import dateutils, logger, status


# letters typed before the drugs are searched
MIN_DRUG_SEARCH = 3
# the worklist counts its matches up to this: the closed admissions grow
# without end, and counting them all could outlast the request
COUNT_LIMIT = 5000


def _check_feature():
    if not feature_service.has_feature(FeatureEnum.INFECTION_CONTROL):
        raise ValidationError(
            "Controle de infecção não está habilitado",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )


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


def _reason_name(reason, parent_name: str | None) -> str:
    return (
        f"{parent_name} - {reason.description}" if parent_name else reason.description
    )


def _serialize_evaluation(
    evaluation: AntimicrobialEvaluation,
    names: dict,
    reason_names: dict | None = None,
    interventions: dict | None = None,
    drug_names: dict | None = None,
) -> dict:
    reason_names = reason_names or {}
    interventions = interventions or {}
    drug_names = drug_names or {}
    return {
        "id": str(evaluation.id),
        "idReview": str(evaluation.id_review),
        "idDrug": evaluation.id_drug,
        "idPrescription": str(evaluation.id_prescription),
        "courseStart": dateutils.to_iso(evaluation.course_start),
        "conforming": evaluation.conforming,
        "interventionReasons": [
            {"id": id_reason, "name": reason_names.get(id_reason)}
            for id_reason in evaluation.id_intervention_reasons or []
        ],
        "substituteDrug": (
            {
                "id": evaluation.id_substitute_drug,
                "name": drug_names.get(evaluation.id_substitute_drug),
            }
            if evaluation.id_substitute_drug
            else None
        ),
        "interventions": [
            {"id": str(i.idIntervention), "status": i.status}
            for i in interventions.get(evaluation.id, [])
        ],
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


def _get_state(
    admission_number: int,
    now: datetime,
    admission_courses: rule.AdmissionCourses | None = None,
) -> dict:
    """The follow-up of an admission: status, open reasons, reviews and the
    evaluations of each antimicrobial course.

    Courses are listed by drug and start, the same key the antimicrobial
    timeline uses, so the page can place each evaluation on its course. The
    page passes the courses it already loaded for the timeline.
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
    names = user_repository.get_user_names(
        {r.created_by for r in reviews} | {e.created_by for e in evaluations}
    )
    reason_names = {
        reason.id: _reason_name(reason, parent_name)
        for reason, parent_name in infection_control_repository.get_intervention_reasons(
            {r for e in evaluations for r in e.id_intervention_reasons or []}
        )
    }
    drug_names = infection_control_repository.get_drug_names(
        {e.id_substitute_drug for e in evaluations if e.id_substitute_drug}
    )
    interventions: dict[int, list] = {}
    for intervention in infection_control_repository.get_evaluation_interventions(
        admission_number=admission_number
    ):
        interventions.setdefault(
            intervention.id_infection_control_evaluation, []
        ).append(intervention)

    if admission_courses is None:
        admission_courses = rule.load_courses(
            admission_number=admission_number, now=now
        )
    courses = []
    for course in admission_courses.courses:
        history = [
            _serialize_evaluation(e, names, reason_names, interventions, drug_names)
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


def _get_follow_up(
    admission_number: int,
    now: datetime,
    admission_courses: rule.AdmissionCourses | None = None,
) -> dict:
    if not feature_service.has_feature(FeatureEnum.INFECTION_CONTROL):
        return {"enabled": False, "admissionNumber": admission_number}

    return _get_state(
        admission_number=admission_number,
        now=now,
        admission_courses=admission_courses,
    )


@has_permission(Permission.READ_INFECTION_CONTROL)
def get_admission_state(admission_number: int):
    """Infection control follow-up of an admission"""
    return _get_follow_up(admission_number=admission_number, now=datetime.now())


@has_permission(Permission.READ_INFECTION_CONTROL)
def get_admission_view(admission_number: int, user_context: User):
    """The infection control page of an admission: the antimicrobial timeline
    and its follow-up, built from the same courses judged at the same time.

    The follow-up runs last, in a savepoint, and never raises: the timeline is
    shown without it (followUp None) and the page offers to load it again.
    """
    now = datetime.now()
    admission_courses = rule.load_courses(admission_number=admission_number, now=now)
    timeline = antimicrobial_timeline_service.get_timeline(
        admission_number=admission_number,
        courses=admission_courses.courses,
        now=now,
        user_context=user_context,
    )

    try:
        with db.session.begin_nested():
            follow_up = _get_follow_up(
                admission_number=admission_number,
                now=now,
                admission_courses=admission_courses,
            )
    except Exception as e:  # noqa: BLE001 - the timeline is shown without it
        logger.backend_logger.exception(str(e))
        # the event the endpoint errors log, which is the one monitored
        logger.backend_logger.warning(
            json.dumps(
                {
                    "event": "backend_exception",
                    "path": "infection_control_service.get_admission_view",
                    "schema": user_context.schema,
                    "user": user_context.id,
                    "message": str(e),
                    "admission_number": admission_number,
                }
            )
        )
        follow_up = None

    return {**timeline, "followUp": follow_up}


def _validate_review(
    request_data: InfectionControlReviewRequest,
    admission_courses: rule.AdmissionCourses,
    now: datetime,
) -> dict:
    """Check the review; returns the intervention reasons it uses, by id"""
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

        if not set(evaluation.triggers) <= rule.OPTIONAL_TRIGGERS:
            raise ValidationError(
                "Gatilho de pendência inválido",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

        # a non-conformity is given its reasons, and may record an intervention
        if evaluation.conforming and (
            evaluation.interventionReasons or evaluation.createIntervention
        ):
            raise ValidationError(
                "Avaliação conforme não tem motivo de não conformidade",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

        if not evaluation.conforming and not evaluation.interventionReasons:
            raise ValidationError(
                "Informe o motivo da não conformidade",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

    id_reasons = {
        id_reason
        for evaluation in request_data.evaluations
        for id_reason in evaluation.interventionReasons
    }
    reasons = {
        reason.id: reason
        for reason, _ in infection_control_repository.get_intervention_reasons(
            id_reasons
        )
        if reason.active and reason.infection_control
    }
    if id_reasons - reasons.keys():
        raise ValidationError(
            "Motivo de não conformidade inválido",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    # a reason related to another drug takes a substitute; a substitution, or
    # one whose relation is required, must have it
    for evaluation in request_data.evaluations:
        chosen = [reasons[id_reason] for id_reason in evaluation.interventionReasons]
        relation_types = {reason.relation_type for reason in chosen}
        if any(reason.substitution for reason in chosen):
            relation_types.add(InterventionReasonRelationTypeEnum.REQUIRED.value)
        if evaluation.substituteDrug is None:
            if InterventionReasonRelationTypeEnum.REQUIRED.value in relation_types:
                raise ValidationError(
                    "Informe o medicamento substituto",
                    "errors.invalidParams",
                    status.HTTP_400_BAD_REQUEST,
                )
        elif not relation_types & {
            InterventionReasonRelationTypeEnum.OPTIONAL.value,
            InterventionReasonRelationTypeEnum.REQUIRED.value,
        }:
            raise ValidationError(
                "Os motivos não indicam medicamento substituto",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

    # the substitute is another antimicrobial
    id_substitutes = {
        evaluation.substituteDrug
        for evaluation in request_data.evaluations
        if evaluation.substituteDrug is not None
    }
    antimicrobials = {
        id_drug
        for id_drug, _ in infection_control_repository.search_antimicrobials(
            id_drugs=id_substitutes, limit=len(id_substitutes)
        )
    }
    if id_substitutes - antimicrobials:
        raise ValidationError(
            "O medicamento substituto deve ser um antimicrobiano",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    return reasons


def _record_intervention(
    evaluation: AntimicrobialEvaluation,
    reasons: list,
    id_department: int | None,
    user_context: User,
):
    """Record the non-conformity as an intervention on the drug, as the
    prescription screening would, kept by infection control"""
    # a record of the past would land on the drug prescribed now
    if evaluation.closing_type == AntimicrobialEvaluationClosingEnum.RETROACTIVE.value:
        raise ValidationError(
            "Avaliação retroativa não registra intervenção",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    intervention_service.create_drug_intervention(
        user_context=user_context,
        id_prescription_drug=evaluation.id_prescription_drug,
        admission_number=evaluation.admission_number,
        id_intervention_reason=evaluation.id_intervention_reasons,
        reasons=reasons,
        id_department=id_department,
        observation=evaluation.notes,
        id_infection_control_evaluation=evaluation.id,
        interactions=(
            [evaluation.id_substitute_drug] if evaluation.id_substitute_drug else None
        ),
    )


@has_permission(Permission.WRITE_INFECTION_CONTROL)
def save_review(request_data: InfectionControlReviewRequest, user_context: User):
    """Record a review: evaluate running antimicrobials, schedule the next
    review and bring the admission status up to date"""
    _check_feature()

    now = datetime.now()
    admission_number = request_data.admissionNumber
    admission_courses = rule.load_courses(admission_number=admission_number, now=now)
    reasons = _validate_review(
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

    id_department = None
    for evaluation_data in request_data.evaluations:
        evaluation = rule.record_evaluation(
            review=review,
            course=admission_courses.ongoing_course(evaluation_data.idDrug),
            evaluation_data=evaluation_data,
            active_evaluations=active_evaluations,
            open_pendings=open_pendings,
            user_id=user_context.id,
            now=now,
        )

        if evaluation_data.createIntervention:
            if id_department is None:
                id_department = intervention_service.get_current_department(
                    admission_number
                )
            _record_intervention(
                evaluation=evaluation,
                reasons=[reasons[r] for r in evaluation.id_intervention_reasons],
                id_department=id_department,
                user_context=user_context,
            )

    rule.resolve_on_review(
        review=review, open_pendings=open_pendings, user_id=user_context.id, now=now
    )

    rule.apply_rule(
        admission=admission,
        admission_courses=admission_courses,
        origin=InfectionControlOriginEnum.REVIEW,
        user_id=user_context.id,
    )

    return _get_state(admission_number=admission_number, now=now)


@has_permission(Permission.READ_PRESCRIPTION)
def search_antimicrobials(term: str | None):
    """Antimicrobials by name, to recommend one instead of another"""
    _check_feature()

    term = (term or "").strip()
    if len(term) < MIN_DRUG_SEARCH:
        return []

    return [
        {"id": id_drug, "name": name}
        for id_drug, name in infection_control_repository.search_antimicrobials(
            term=term
        )
    ]


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
    now = datetime.now()
    rows = infection_control_repository.list_admissions(
        statuses=statuses, filters=request_data, now=now
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

    admissions = []
    for row in rows:
        admission = row.InfectionControlAdmission
        patient = row.Patient
        admissions.append(
            {
                "admissionNumber": admission.admission_number,
                "idPatient": str(patient.idPatient) if patient else None,
                "birthdate": dateutils.to_iso(patient.birthdate) if patient else None,
                "gender": patient.gender if patient else None,
                "admissionDate": (
                    dateutils.to_iso(patient.admissionDate) if patient else None
                ),
                "bed": row.bed,
                "department": row.department,
                "status": admission.status,
                "statusDate": dateutils.to_iso(admission.status_date),
                "nextReviewDate": dateutils.to_iso(admission.next_review_date),
                "earliestValidUntil": dateutils.to_iso(
                    validity.get(admission.admission_number)
                ),
                "pendings": pendings_by_admission.get(admission.admission_number, []),
            }
        )

    # the list holds every match from the offset unless the limit cut it (an
    # empty page past the offset says nothing)
    if len(rows) < request_data.limit and (rows or request_data.offset == 0):
        count = request_data.offset + len(rows)
    else:
        count = infection_control_repository.count_admissions(
            statuses=statuses,
            filters=request_data,
            now=now,
            limit=COUNT_LIMIT + 1,
        )

    return {
        # all the matching admissions, up to COUNT_LIMIT: more than listed when
        # the limit cut the list
        "count": min(count, COUNT_LIMIT),
        # more than COUNT_LIMIT match
        "countLimited": count > COUNT_LIMIT,
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
