"""Repository: infection control follow-up (ci_* tables)"""

from datetime import datetime

from sqlalchemy import and_, func, or_, text
from sqlalchemy.dialects.postgresql import insert

from models.appendix import Department
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
from models.main import DrugAttributes, db
from models.prescription import Patient, Prescription, PrescriptionDrug


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


def lock_admission(
    admission_number: int, lock_timeout_ms: int | None = None
) -> InfectionControlAdmission | None:
    """The admission record, locked until the end of the transaction.

    Every writer (prescalc, review save, the job) changes the pending reasons
    and the status under this lock, so the two never disagree. With
    lock_timeout_ms the wait is bounded: a timeout raises OperationalError.
    """
    if lock_timeout_ms is not None:
        # set_config(..., true) is SET LOCAL with a bind param
        db.session.execute(
            text("SELECT set_config('lock_timeout', :timeout, true)"),
            {"timeout": f"{int(lock_timeout_ms)}ms"},
        )

    admission = (
        db.session.query(InfectionControlAdmission)
        .filter(InfectionControlAdmission.admission_number == admission_number)
        .with_for_update()
        .first()
    )

    if lock_timeout_ms is not None:
        # restore it so the timeout doesn't leak into later waits of the transaction
        db.session.execute(text("SET LOCAL lock_timeout = DEFAULT"))

    return admission


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


def list_admissions(statuses: list[int], limit: int, offset: int):
    """Followed admissions with the given statuses, longest in that status first"""
    return (
        db.session.query(InfectionControlAdmission, Patient)
        .outerjoin(
            Patient,
            Patient.admissionNumber == InfectionControlAdmission.admission_number,
        )
        .filter(InfectionControlAdmission.status.in_(statuses))
        .order_by(
            InfectionControlAdmission.status_date,
            InfectionControlAdmission.admission_number,
        )
        .limit(limit)
        .offset(offset)
        .all()
    )


def count_admissions(statuses: list[int]) -> int:
    """How many followed admissions have the given statuses"""
    return (
        db.session.query(func.count(InfectionControlAdmission.admission_number))
        .filter(InfectionControlAdmission.status.in_(statuses))
        .scalar()
    )


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
