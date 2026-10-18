"""Repository: infection control follow-up (ci_* tables)"""

from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    and_,
    column,
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
from models.requests.infection_control_request import InfectionControlListRequest


def create_admission(
    admission_number: int, origin: int, user_id: int, now: datetime
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
            created_at=now,
            created_by=user_id,
        )
        .on_conflict_do_nothing(index_elements=["nratendimento"])
    )
    return db.session.execute(stmt).rowcount > 0


@contextmanager
def lock_timeout(lock_timeout_ms: int | None):
    """Bound the lock waits inside the block: a timeout raises OperationalError.

    Restored when the block succeeds, so it doesn't leak into later waits of the
    transaction. When it fails the transaction (or the savepoint the block runs
    in) is rolled back, and that undoes the setting too.
    """
    if lock_timeout_ms is None:
        yield
        return

    # set_config(..., true) is SET LOCAL with a bind param
    db.session.execute(
        text("SELECT set_config('lock_timeout', :timeout, true)"),
        {"timeout": f"{int(lock_timeout_ms)}ms"},
    )
    yield
    db.session.execute(text("SET LOCAL lock_timeout = DEFAULT"))


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
    followed admissions"""
    if filters.idDepartment:
        # the department of the latest real prescription, as the department
        # shown in the worklist (get_last_prescriptions)
        last_prescription = (
            db.session.query(
                Prescription.admissionNumber.label("admission_number"),
                Prescription.idDepartment.label("id_department"),
            )
            .join(
                InfectionControlAdmission,
                InfectionControlAdmission.admission_number
                == Prescription.admissionNumber,
            )
            .filter(or_(Prescription.agg == None, Prescription.agg == False))
            .filter(Prescription.concilia == None)
            .distinct(Prescription.admissionNumber)
            .order_by(Prescription.admissionNumber, Prescription.date.desc())
            .subquery()
        )
        query = query.join(
            last_prescription,
            last_prescription.c.admission_number
            == InfectionControlAdmission.admission_number,
        ).filter(last_prescription.c.id_department.in_(filters.idDepartment))

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


def _filter_features(query, filters: InfectionControlListRequest, now: datetime):
    """Apply the worklist filters kept on the record by the rule (indicadores),
    so the worklist doesn't join the prescriptions of every admission.

    The antimicrobial filters (drug, substance, AWaRe level, treatment day) are
    met by one running course: amoxicillin on D1 is the amoxicillin course on
    its first day, not amoxicillin and some other antimicrobial on D1.
    """
    course = (
        func.jsonb_array_elements(InfectionControlAdmission.features["courses"])
        .table_valued(column("value", JSONB))
        .alias("course")
    )
    value = course.c.value
    conditions = []

    if filters.idDrug:
        conditions.append(value["idDrug"].astext.cast(BigInteger).in_(filters.idDrug))

    if filters.idSubstance:
        conditions.append(
            value["idSubstance"].astext.cast(BigInteger).in_(filters.idSubstance)
        )

    if filters.awareLevels:
        conditions.append(
            value["awareLevel"].astext.cast(Integer).in_(filters.awareLevels)
        )

    # the course is on day N, counted as in the timeline (D1 is the first 24
    # hours), once more than N - 1 days passed since its start and until N days
    # passed
    start = value["start"].astext.cast(DateTime)
    if filters.treatmentDayFrom and filters.treatmentDayFrom > 1:
        conditions.append(start < now - timedelta(days=filters.treatmentDayFrom - 1))

    if filters.treatmentDayTo:
        conditions.append(start >= now - timedelta(days=filters.treatmentDayTo))

    if conditions:
        query = query.filter(
            db.session.query(course).filter(and_(*conditions)).exists()
        )

    if filters.nonConforming:
        query = query.filter(
            InfectionControlAdmission.features["nonConforming"].as_boolean() == True
        )

    return query


def list_admissions(
    statuses: list[int],
    filters: InfectionControlListRequest,
    now: datetime,
):
    """Followed admissions with the given statuses matching the worklist
    filters, longest in that status first"""
    query = db.session.query(InfectionControlAdmission, Patient).outerjoin(
        Patient,
        Patient.admissionNumber == InfectionControlAdmission.admission_number,
    )
    query = _filter_admissions(query=query, filters=filters, now=now)

    return (
        query.filter(InfectionControlAdmission.status.in_(statuses))
        .order_by(
            InfectionControlAdmission.status_date,
            InfectionControlAdmission.admission_number,
        )
        .limit(filters.limit)
        .offset(filters.offset)
        .all()
    )


def count_admissions(
    statuses: list[int], filters: InfectionControlListRequest, now: datetime
) -> int:
    """How many followed admissions with the given statuses match the worklist
    filters"""
    query = db.session.query(func.count(InfectionControlAdmission.admission_number))
    query = _filter_admissions(query=query, filters=filters, now=now)

    return query.filter(InfectionControlAdmission.status.in_(statuses)).scalar()


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


def get_last_prescriptions(admission_numbers: list[int]) -> dict:
    """Latest real prescription of each admission with its department name"""
    if not admission_numbers:
        return {}

    rows = (
        db.session.query(Prescription, Department.name.label("department"))
        .outerjoin(
            Department,
            and_(
                Department.id == Prescription.idDepartment,
                Department.idHospital == Prescription.idHospital,
            ),
        )
        .filter(Prescription.admissionNumber.in_(admission_numbers))
        .filter(or_(Prescription.agg == None, Prescription.agg == False))
        .filter(Prescription.concilia == None)
        .distinct(Prescription.admissionNumber)
        .order_by(Prescription.admissionNumber, Prescription.date.desc())
        .all()
    )
    return {row.Prescription.admissionNumber: row for row in rows}
