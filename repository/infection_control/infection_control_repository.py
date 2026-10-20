"""Repository: infection control follow-up (ci_* tables)"""

from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    and_,
    case,
    column,
    false,
    func,
    or_,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert

from models.appendix import Department, InterventionReason
from models.enums import (
    AntimicrobialEvaluationStatusEnum,
    InfectionControlStatusEnum,
)
from models.infection_control import (
    AntimicrobialEvaluation,
    InfectionControlAdmission,
    InfectionControlPending,
    InfectionControlReview,
)
from models.main import Drug, DrugAttributes, db
from models.prescription import Intervention, Patient, Prescription, PrescriptionDrug
from models.requests.infection_control_request import (
    AntimicrobialCriterionRequest,
    InfectionControlListRequest,
)


def create_admission(
    admission_number: int,
    origin: int,
    user_id: int,
    now: datetime,
    id_last_prescription: int | None = None,
) -> bool:
    """Create the admission record as pending, unless it already exists.

    Returns True when it was created.
    """
    stmt = (
        insert(InfectionControlAdmission)
        .values(
            admission_number=admission_number,
            status=InfectionControlStatusEnum.PENDING.value,
            status_date=now,
            origin=origin,
            recalculated_at=now,
            id_last_prescription=id_last_prescription,
            created_at=now,
            created_by=user_id,
        )
        .on_conflict_do_nothing(index_elements=["nratendimento"])
    )
    return db.session.execute(stmt).rowcount > 0


@contextmanager
def _local_timeout(setting: str, timeout_ms: int | None):
    """Set a timeout (lock_timeout, statement_timeout) inside the block: running
    out raises OperationalError.

    Restored when the block succeeds, so it doesn't leak into the rest of the
    transaction. When it fails the transaction (or the savepoint the block runs
    in) is rolled back, and that undoes the setting too.
    """
    if timeout_ms is None:
        yield
        return

    # set_config(..., true) is SET LOCAL with a bind param
    db.session.execute(
        text("SELECT set_config(:setting, :timeout, true)"),
        {"setting": setting, "timeout": f"{int(timeout_ms)}ms"},
    )
    yield
    db.session.execute(text(f"SET LOCAL {setting} = DEFAULT"))


def lock_timeout(lock_timeout_ms: int | None):
    """Bound the lock waits inside the block (see _local_timeout)"""
    return _local_timeout("lock_timeout", lock_timeout_ms)


def statement_timeout(statement_timeout_ms: int | None):
    """Bound each query inside the block (see _local_timeout)"""
    return _local_timeout("statement_timeout", statement_timeout_ms)


def lock_admission(
    admission_number: int, lock_timeout_ms: int | None = None
) -> InfectionControlAdmission | None:
    """The admission record, locked until the end of the transaction.

    Every writer (review save, the job) changes the pending reasons and the
    status under this lock, so the two never disagree. With lock_timeout_ms
    the wait is bounded: a timeout raises OperationalError.
    """
    with lock_timeout(lock_timeout_ms):
        return (
            db.session.query(InfectionControlAdmission)
            .filter(InfectionControlAdmission.admission_number == admission_number)
            .with_for_update()
            .first()
        )


def is_discharged(admission_number: int, now: datetime) -> bool:
    """Whether the patient of an admission was discharged by `now`"""
    discharge_date = (
        db.session.query(Patient.dischargeDate)
        .filter(Patient.admissionNumber == admission_number)
        .scalar()
    )
    return discharge_date is not None and discharge_date <= now


def reopen_admission(admission_number: int, user_id: int, now: datetime):
    """Make a closed admission record pending again.

    Only a closed record is touched: a pending or revised one is left as is
    without waiting for its lock. Returns the reopened row (with its last
    review), or None when the record is not closed.
    """
    stmt = (
        update(InfectionControlAdmission)
        .where(InfectionControlAdmission.admission_number == admission_number)
        .where(
            InfectionControlAdmission.status == InfectionControlStatusEnum.CLOSED.value
        )
        .values(
            status=InfectionControlStatusEnum.PENDING.value,
            status_date=now,
            updated_at=now,
            updated_by=user_id,
        )
        .returning(InfectionControlAdmission.id_last_review)
        .execution_options(synchronize_session=False)
    )
    return db.session.execute(stmt).first()


def get_last_prescription_day_id(admission_number: int) -> int | None:
    """The latest prescription-day of an admission, whose department and bed
    (of the last prescription it gathered) the worklist filters by and shows"""
    return (
        db.session.query(Prescription.id)
        .filter(Prescription.admissionNumber == admission_number)
        .filter(Prescription.agg == True)
        .order_by(Prescription.date.desc(), Prescription.id.desc())
        .limit(1)
        .scalar()
    )


def open_pending(
    admission_number: int,
    pending_type: int,
    origin: int,
    user_id: int,
    now: datetime,
    id_drug: int | None = None,
    id_prescription: int | None = None,
    id_evaluation: int | None = None,
    details: dict | None = None,
) -> bool:
    """Open a pending reason, unless the same one is already open.

    The partial unique index on the open reasons keeps one per admission, type
    and reference, so a drug repeated on every daily prescription stays a
    single reason. Returns True when it was opened.
    """
    stmt = (
        insert(InfectionControlPending)
        .values(
            admission_number=admission_number,
            pending_type=pending_type,
            origin=origin,
            id_drug=id_drug,
            id_prescription=id_prescription,
            id_evaluation=id_evaluation,
            details=details,
            created_at=now,
            created_by=user_id,
        )
        .on_conflict_do_nothing()
    )
    return db.session.execute(stmt).rowcount > 0


def get_open_pendings(admission_number: int) -> list[InfectionControlPending]:
    """Open pending reasons of an admission, oldest first"""
    return (
        db.session.query(InfectionControlPending)
        .filter(InfectionControlPending.admission_number == admission_number)
        .filter(InfectionControlPending.resolved_at == None)
        .order_by(InfectionControlPending.created_at, InfectionControlPending.id)
        .all()
    )


def get_active_evaluations(admission_number: int) -> list[AntimicrobialEvaluation]:
    """Evaluations of an admission that are still in force"""
    return (
        db.session.query(AntimicrobialEvaluation)
        .filter(AntimicrobialEvaluation.admission_number == admission_number)
        .filter(
            AntimicrobialEvaluation.status
            == AntimicrobialEvaluationStatusEnum.ACTIVE.value
        )
        .order_by(AntimicrobialEvaluation.created_at)
        .all()
    )


def get_evaluations(admission_number: int) -> list[AntimicrobialEvaluation]:
    """Every evaluation of an admission, oldest first"""
    return (
        db.session.query(AntimicrobialEvaluation)
        .filter(AntimicrobialEvaluation.admission_number == admission_number)
        .order_by(AntimicrobialEvaluation.created_at, AntimicrobialEvaluation.id)
        .all()
    )


def get_intervention_reasons(
    id_reasons: set[int],
) -> list[tuple[InterventionReason, str | None]]:
    """Intervention reasons, each with the name of its parent reason"""
    if not id_reasons:
        return []

    parent = db.aliased(InterventionReason)
    return (
        db.session.query(InterventionReason, parent.description)
        .outerjoin(parent, InterventionReason.mamy == parent.id)
        .filter(InterventionReason.id.in_(id_reasons))
        .all()
    )


def get_drug_names(id_drugs: set[int]) -> dict[int, str]:
    """Names of drugs, by id"""
    if not id_drugs:
        return {}

    return dict(
        db.session.query(Drug.id, Drug.name).filter(Drug.id.in_(id_drugs)).all()
    )


def search_antimicrobials(
    term: str | None = None, id_drugs: set[int] | None = None, limit: int = 50
) -> list[tuple[int, str]]:
    """Drugs flagged antimicrobial (antimicro) in some segment, by name"""
    is_antimicrobial = (
        db.session.query(DrugAttributes.idDrug)
        .filter(DrugAttributes.idDrug == Drug.id)
        .filter(DrugAttributes.antimicro == True)
        .exists()
    )
    query = db.session.query(Drug.id, Drug.name).filter(is_antimicrobial)
    if term:
        query = query.filter(Drug.name.ilike(f"%{term}%"))
    if id_drugs is not None:
        query = query.filter(Drug.id.in_(id_drugs))

    return query.order_by(Drug.name, Drug.id).limit(limit).all()


def get_evaluation_interventions(admission_number: int) -> list[Intervention]:
    """Interventions recorded by the reviews of an admission, oldest first;
    the ones undone (status 0) are gone, as in the screening"""
    return (
        db.session.query(Intervention)
        .filter(Intervention.admissionNumber == admission_number)
        .filter(Intervention.id_infection_control_evaluation != None)
        .filter(Intervention.status != "0")
        .order_by(Intervention.idIntervention)
        .all()
    )


def get_admission(admission_number: int) -> InfectionControlAdmission | None:
    """The admission record, without locking it"""
    return (
        db.session.query(InfectionControlAdmission)
        .filter(InfectionControlAdmission.admission_number == admission_number)
        .first()
    )


def get_reviews(admission_number: int) -> list[InfectionControlReview]:
    """Reviews of an admission, latest first"""
    return (
        db.session.query(InfectionControlReview)
        .filter(InfectionControlReview.admission_number == admission_number)
        .order_by(InfectionControlReview.created_at.desc())
        .all()
    )


def get_backfill_candidates(since: datetime, after: int, limit: int) -> list[int]:
    """Admissions not yet followed, not discharged, with an antimicrobial
    valid after `since` or an open-ended order not suspended before it, in
    admission number order starting after `after`.

    Candidates only: sync_admission decides whether a course is running.
    """
    query = (
        db.session.query(Prescription.admissionNumber)
        .join(PrescriptionDrug, PrescriptionDrug.idPrescription == Prescription.id)
        .join(
            DrugAttributes,
            and_(
                DrugAttributes.idDrug == PrescriptionDrug.idDrug,
                DrugAttributes.idSegment
                == func.coalesce(PrescriptionDrug.idSegment, Prescription.idSegment),
            ),
        )
        .outerjoin(
            InfectionControlAdmission,
            InfectionControlAdmission.admission_number == Prescription.admissionNumber,
        )
        .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)
        .filter(DrugAttributes.antimicro == True)
        .filter(or_(Prescription.agg == None, Prescription.agg == False))
        .filter(Prescription.concilia == None)
        .filter(
            or_(
                Prescription.expire >= since,
                # open-ended (CPOE) order: running until suspended
                and_(
                    Prescription.expire == None,
                    or_(
                        PrescriptionDrug.suspendedDate == None,
                        PrescriptionDrug.suspendedDate >= since,
                    ),
                ),
            )
        )
        .filter(Prescription.admissionNumber > after)
        .filter(InfectionControlAdmission.admission_number == None)
        .filter(Patient.dischargeDate == None)
        .distinct()
        .order_by(Prescription.admissionNumber)
        .limit(limit)
    )

    return [row.admissionNumber for row in query.all()]


def _filter_admissions(query, filters: InfectionControlListRequest, now: datetime):
    """Apply the worklist filters (all but the status) to a query on the
    followed admissions joined to their latest prescription-day
    (_worklist_query)"""
    if filters.idDepartment:
        # the department shown in the worklist, of the latest prescription-day
        query = query.filter(Prescription.idDepartment.in_(filters.idDepartment))

    if filters.admissionNumbers:
        query = query.filter(
            InfectionControlAdmission.admission_number.in_(filters.admissionNumbers)
        )

    if filters.pendingTypes:
        query = query.filter(
            db.session.query(InfectionControlPending.id)
            .filter(
                InfectionControlPending.admission_number
                == InfectionControlAdmission.admission_number
            )
            .filter(InfectionControlPending.resolved_at == None)
            .filter(InfectionControlPending.pending_type.in_(filters.pendingTypes))
            .exists()
        )

    if filters.overdueReview:
        query = query.filter(InfectionControlAdmission.next_review_date != None).filter(
            InfectionControlAdmission.next_review_date < now
        )

    return _filter_features(query=query, filters=filters, now=now)


def _running_course(conditions: list):
    """Whether a running course kept on the record (indicadores) meets all the
    conditions, given on its value by the caller"""
    course = (
        func.jsonb_array_elements(InfectionControlAdmission.features["courses"])
        .table_valued(column("value", JSONB))
        .alias("course")
    )
    return (
        db.session.query(course)
        .filter(and_(*[condition(course.c.value) for condition in conditions]))
        .exists()
    )


def _criterion_conditions(criterion: AntimicrobialCriterionRequest, now: datetime):
    """The conditions a course meets for one antimicrobial criterion: any of
    its drugs or substances, on a treatment day of its range"""
    conditions = []

    drugs = criterion.idDrug
    substances = criterion.idSubstance
    if drugs or substances:
        conditions.append(
            lambda value: or_(
                value["idDrug"].astext.cast(BigInteger).in_(drugs),
                value["idSubstance"].astext.cast(BigInteger).in_(substances),
            )
        )

    # the course is on day N, counted as in the timeline (D1 is the first 24
    # hours), once more than N - 1 days passed since its start and until N days
    # passed
    day_from = criterion.treatmentDayFrom
    if day_from and day_from > 1:
        conditions.append(
            lambda value: (
                value["start"].astext.cast(DateTime)
                < now - timedelta(days=day_from - 1)
            )
        )

    day_to = criterion.treatmentDayTo
    if day_to:
        conditions.append(
            lambda value: (
                value["start"].astext.cast(DateTime) >= now - timedelta(days=day_to)
            )
        )

    return conditions


def _filter_features(query, filters: InfectionControlListRequest, now: datetime):
    """Apply the worklist filters kept on the record by the rule (indicadores),
    so the worklist doesn't join the prescriptions of every admission.

    Each antimicrobial criterion is met by a running course of its own: the
    drug and the treatment day of a criterion go together (amoxicillin on D1 is
    the amoxicillin course on its first day). Amoxicillin on D1 with vancomycin
    on D2 asks for either course, or for both with antimicrobialsMatchAll.
    """
    courses = [
        _running_course(conditions)
        for conditions in (
            _criterion_conditions(criterion=criterion, now=now)
            for criterion in filters.antimicrobials
        )
        if conditions
    ]
    if courses:
        query = query.filter(
            and_(*courses) if filters.antimicrobialsMatchAll else or_(*courses)
        )

    if filters.awareLevels:
        levels = filters.awareLevels
        query = query.filter(
            _running_course(
                [lambda value: value["awareLevel"].astext.cast(Integer).in_(levels)]
            )
        )

    if filters.nonConforming:
        query = query.filter(
            InfectionControlAdmission.features["nonConforming"].as_boolean() == True
        )

    return query


def _asks_open_only(filters: InfectionControlListRequest, now: datetime) -> bool:
    """Whether the filters ask for what only an open record has: a running
    antimicrobial, an open reason or an evaluation in force. A record is
    closed when nothing runs, so it has none of them"""
    return bool(
        filters.pendingTypes
        or filters.awareLevels
        or filters.nonConforming
        or any(
            _criterion_conditions(criterion=criterion, now=now)
            for criterion in filters.antimicrobials
        )
    )


def _status_condition(
    statuses: list[int], filters: InfectionControlListRequest, now: datetime
):
    """The followed admissions of the given statuses. The closed ones only
    within filters.closedDays of closing (unless asked by admission number),
    and none when the filters ask for what only an open record has"""
    closed = InfectionControlStatusEnum.CLOSED.value
    conditions = []

    open_statuses = [s for s in statuses if s != closed]
    if open_statuses:
        conditions.append(InfectionControlAdmission.status.in_(open_statuses))

    if closed in statuses and not _asks_open_only(filters=filters, now=now):
        closed_condition = InfectionControlAdmission.status == closed
        if not filters.admissionNumbers:
            closed_condition = and_(
                closed_condition,
                InfectionControlAdmission.status_date
                >= now - timedelta(days=filters.closedDays),
            )
        conditions.append(closed_condition)

    return or_(*conditions) if conditions else false()


def _worklist_query(
    entities: list,
    statuses: list[int],
    filters: InfectionControlListRequest,
    now: datetime,
):
    """Followed admissions with the given statuses matching the worklist
    filters, joined to their latest prescription-day (none yet on a record
    the job hasn't pointed)"""
    query = (
        db.session.query(*entities)
        .select_from(InfectionControlAdmission)
        .outerjoin(
            Prescription,
            Prescription.id == InfectionControlAdmission.id_last_prescription,
        )
        .filter(_status_condition(statuses=statuses, filters=filters, now=now))
    )
    return _filter_admissions(query=query, filters=filters, now=now)


def list_admissions(
    statuses: list[int],
    filters: InfectionControlListRequest,
    now: datetime,
):
    """Followed admissions with the given statuses matching the worklist
    filters, with the bed and department of their latest prescription-day.
    The open ones first, longest in their status first, then the closed ones,
    latest closed first"""
    query = (
        _worklist_query(
            entities=[
                InfectionControlAdmission,
                Patient,
                Prescription.bed.label("bed"),
                Department.name.label("department"),
            ],
            statuses=statuses,
            filters=filters,
            now=now,
        )
        .outerjoin(
            Patient,
            Patient.admissionNumber == InfectionControlAdmission.admission_number,
        )
        .outerjoin(
            Department,
            and_(
                Department.id == Prescription.idDepartment,
                Department.idHospital == Prescription.idHospital,
            ),
        )
    )

    is_closed = (
        InfectionControlAdmission.status == InfectionControlStatusEnum.CLOSED.value
    )
    return (
        query.order_by(
            is_closed,
            case((is_closed, None), else_=InfectionControlAdmission.status_date),
            InfectionControlAdmission.status_date.desc(),
            InfectionControlAdmission.admission_number,
        )
        .limit(filters.limit)
        .offset(filters.offset)
        .all()
    )


def count_admissions(
    statuses: list[int],
    filters: InfectionControlListRequest,
    now: datetime,
    limit: int,
) -> int:
    """How many followed admissions with the given statuses match the worklist
    filters, counted up to `limit`: the closed ones grow without end"""
    matches = (
        _worklist_query(
            entities=[InfectionControlAdmission.admission_number],
            statuses=statuses,
            filters=filters,
            now=now,
        )
        .limit(limit)
        .subquery()
    )
    return db.session.query(func.count()).select_from(matches).scalar()


def get_open_pendings_by_admission(
    admission_numbers: list[int],
) -> list[InfectionControlPending]:
    """Open pending reasons of several admissions"""
    if not admission_numbers:
        return []

    return (
        db.session.query(InfectionControlPending)
        .filter(InfectionControlPending.admission_number.in_(admission_numbers))
        .filter(InfectionControlPending.resolved_at == None)
        .order_by(InfectionControlPending.created_at, InfectionControlPending.id)
        .all()
    )


def get_earliest_validity_by_admission(admission_numbers: list[int]) -> dict:
    """The earliest valid-until date among the active evaluations of each admission"""
    if not admission_numbers:
        return {}

    rows = (
        db.session.query(
            AntimicrobialEvaluation.admission_number,
            func.min(AntimicrobialEvaluation.valid_until),
        )
        .filter(AntimicrobialEvaluation.admission_number.in_(admission_numbers))
        .filter(
            AntimicrobialEvaluation.status
            == AntimicrobialEvaluationStatusEnum.ACTIVE.value
        )
        .group_by(AntimicrobialEvaluation.admission_number)
        .all()
    )
    return {admission_number: valid_until for admission_number, valid_until in rows}
