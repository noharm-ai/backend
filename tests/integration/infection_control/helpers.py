"""Helpers of the infection control follow-up tests: constants, prescribing,
running prescalc and the job, and reading the ci_* tables"""

import json
from datetime import datetime, timedelta

from sqlalchemy import text

from models.enums import (
    InfectionControlOriginEnum,
    InfectionControlPendingTypeEnum,
    InfectionControlStatusEnum,
)
from models.main import db, dbSession
from services.infection_control import infection_control_status_service
from static import prescalc
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from utils.static_context import static_user_context

ADULT_SEGMENT = 1
CPOE_SEGMENT = 2
# a trigger sets the prescription segment from its department (segmentosetor)
DEPARTMENT_BY_SEGMENT = {ADULT_SEGMENT: 1, CPOE_SEGMENT: 3}
ANTIMICROBIAL_DRUG = 1
OTHER_DRUG = 4
PATIENT_ID = 100702

PENDING = InfectionControlStatusEnum.PENDING.value
REVISED = InfectionControlStatusEnum.REVISED.value
CLOSED = InfectionControlStatusEnum.CLOSED.value
NEVER_REVIEWED = InfectionControlPendingTypeEnum.NEVER_REVIEWED.value
NO_EVALUATION = InfectionControlPendingTypeEnum.NO_EVALUATION.value
EXPIRED = InfectionControlPendingTypeEnum.EXPIRED.value
SCHEDULED_DATE = InfectionControlPendingTypeEnum.SCHEDULED_DATE.value
POSOLOGY_CHANGED = InfectionControlPendingTypeEnum.POSOLOGY_CHANGED.value


def _day(offset):
    """08:00 of today + offset days"""
    return datetime.now().replace(
        hour=8, minute=0, second=0, microsecond=0
    ) + timedelta(days=offset)


def _prescribe(
    admission_number,
    date,
    expire,
    drugs=(ANTIMICROBIAL_DRUG,),
    id_segment=ADULT_SEGMENT,
    dose=2.0,
):
    """One prescription holding the given drugs"""
    id_prescription = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1

    create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=PATIENT_ID,
        idSegment=id_segment,
        idDepartment=DEPARTMENT_BY_SEGMENT[id_segment],
        date=date,
        expire=expire,
    )
    for index, id_drug in enumerate(drugs, start=1):
        create_prescription_drug(
            id=int(f"{id_prescription}{index:03d}"),
            idPrescription=id_prescription,
            idDrug=id_drug,
            idSegment=id_segment,
            idMeasureUnit="1",
            idFrequency="3",
            dose=dose,
        )
    return id_prescription


def _prescribe_today(admission_number, drugs=(ANTIMICROBIAL_DRUG,), job=True):
    """A daily prescription valid from yesterday until tomorrow, run through
    prescalc and then (unless job=False) the job"""
    id_prescription = _prescribe(admission_number, _day(-1), _day(1), drugs=drugs)
    _prescalc(id_prescription)
    if job:
        _run_job(admission_number)
    return id_prescription


def _prescalc(id_prescription):
    response = json.loads(
        prescalc(
            {"schema": "demo", "id_prescription": id_prescription, "force": True}, None
        )
    )
    assert response["status"] == "success", response
    session_commit()


def _run_job(admission_number):
    """Apply the rule to the admission, as the scheduled job does"""
    with static_user_context("demo"):
        dbSession.setSchema("demo")
        infection_control_status_service.sync_admission(
            admission_number=admission_number,
            origin=InfectionControlOriginEnum.JOB,
            user_id=0,
        )
        db.session.commit()
        db.session.remove()
    session_commit()


def _suspend(id_prescription):
    session.execute(
        text("UPDATE demo.presmed SET dtsuspensao = :date WHERE fkprescricao = :id"),
        {"date": datetime.now() - timedelta(hours=1), "id": id_prescription},
    )
    session_commit()


def _discharge(admission_number):
    session.execute(
        text("UPDATE demo.pessoa SET dtalta = :date WHERE nratendimento = :admission"),
        {"date": datetime.now() - timedelta(hours=1), "admission": admission_number},
    )
    session_commit()


def _hold_record(admission_number):
    """Lock the admission record in the test session, as a review save would"""
    session.execute(
        text(
            "SELECT * FROM demo.ci_atendimento "
            "WHERE nratendimento = :admission FOR UPDATE"
        ),
        {"admission": admission_number},
    )


def _record(admission_number):
    return (
        session.execute(
            text("SELECT * FROM demo.ci_atendimento WHERE nratendimento = :admission"),
            {"admission": admission_number},
        )
        .mappings()
        .first()
    )


def _open_pendings(admission_number):
    return (
        session.execute(
            text(
                "SELECT * FROM demo.ci_pendencia "
                "WHERE nratendimento = :admission AND dt_resolucao IS NULL "
                "ORDER BY idci_pendencia"
            ),
            {"admission": admission_number},
        )
        .mappings()
        .all()
    )


def _pendings(admission_number):
    return (
        session.execute(
            text(
                "SELECT * FROM demo.ci_pendencia WHERE nratendimento = :admission "
                "ORDER BY idci_pendencia"
            ),
            {"admission": admission_number},
        )
        .mappings()
        .all()
    )


def _evaluations(admission_number):
    return (
        session.execute(
            text(
                "SELECT * FROM demo.ci_avaliacao_atm WHERE nratendimento = :admission "
                "ORDER BY idci_avaliacao_atm"
            ),
            {"admission": admission_number},
        )
        .mappings()
        .all()
    )


def _set(table, admission_number, **values):
    """Move dates of a follow-up row, to reach what only time would"""
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    session.execute(
        text(f"UPDATE demo.{table} SET {assignments} WHERE nratendimento = :admission"),
        {**values, "admission": admission_number},
    )
    session_commit()


def _review(client, headers, admission_number, evaluations=(), **kwargs):
    payload = {
        "admissionNumber": admission_number,
        "notes": kwargs.get("notes"),
        "nextReviewDate": kwargs.get("next_review_date"),
        "evaluations": [
            {
                "idDrug": id_drug,
                "conforming": True,
                "notes": "Indicação adequada",
                "validFrom": kwargs.get("valid_from"),
                "validUntil": kwargs.get(
                    "valid_until", (datetime.now() + timedelta(days=7)).isoformat()
                ),
                "triggers": kwargs.get("triggers", []),
            }
            for id_drug in evaluations
        ],
    }
    response = client.post("/infection-control/review", json=payload, headers=headers)
    session_commit()
    return response
