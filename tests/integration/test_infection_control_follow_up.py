"""Tests: infection control follow-up (ci_* tables)

An admission with a running antimicrobial is followed: prescalc creates its
record as pending and never reviewed (or reopens a closed one); the rule
(applied by the scheduled job in backend-private, the review save and the
backfill) opens one reason per drug without an evaluation and follows stops,
new drugs and discharge; the infectologist's
review evaluates drugs, settles reasons and sets the status (pending while a
reason is open, revised when none is left, closed when no antimicrobial is
running anymore).

Seed data used (demo schema): drug 1 (AMPICILINA + SULBACTAM) is antimicrobial
on segment 1, drug 4 (BISACODIL) is not; the ``second_antimicrobial`` fixture
flags drug 4 as antimicrobial to have two drugs. Segment 2 is the CPOE segment;
the ``cpoe_antimicrobial`` fixture flags drug 1 as antimicrobial there too.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import (
    AntimicrobialEvaluationClosingEnum,
    AntimicrobialEvaluationStatusEnum,
    FeatureEnum,
    InfectionControlOriginEnum,
    InfectionControlPendingTypeEnum,
    InfectionControlResolutionEnum,
    InfectionControlStatusEnum,
)
from models.main import db, dbSession
from security.role import Role
from services.infection_control import infection_control_status_service
from static import atendcalc, prescalc
from tests.conftest import get_access, make_headers, session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from utils import status
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


# ─── fixtures ─────────────────────────────────────────────────────────────────


def _read_features():
    row = session.execute(
        text("SELECT valor FROM demo.memoria WHERE tipo = 'features'")
    ).first()
    return list(row[0]) if row else []


def _write_features(features):
    session.execute(
        text(
            "UPDATE demo.memoria SET valor = CAST(:value AS json) WHERE tipo = 'features'"
        ),
        {"value": json.dumps(features)},
    )
    session_commit()


@pytest.fixture
def infection_control():
    """Enable INFECTION_CONTROL for the demo schema"""
    original = _read_features()
    _write_features(original + [FeatureEnum.INFECTION_CONTROL.value])
    yield
    _write_features(original)


@pytest.fixture
def admission():
    """A synthetic patient admitted ten days ago"""
    admission_number = test_counters["admission_number"]
    test_counters["admission_number"] += 1

    session.execute(
        text(
            "INSERT INTO demo.pessoa "
            "(fkpessoa, nratendimento, dtinternacao, dtnascimento, sexo, peso) "
            "VALUES (:id_patient, :admission, :admission_date, '1970-05-04', 'F', 70)"
        ),
        {
            "id_patient": PATIENT_ID,
            "admission": admission_number,
            "admission_date": datetime.now() - timedelta(days=10),
        },
    )
    session_commit()

    yield admission_number

    for table in (
        "ci_pendencia",
        "ci_avaliacao_atm",
        "ci_revisao",
        "ci_atendimento",
        "pessoa",
        "pessoa_audit",
    ):
        session.execute(
            text(f"DELETE FROM demo.{table} WHERE nratendimento = :admission"),
            {"admission": admission_number},
        )
    session_commit()


def _flag_antimicrobial(id_drug, id_segment, value):
    session.execute(
        text(
            "UPDATE demo.medatributos SET antimicro = :value "
            "WHERE fkmedicamento = :id_drug AND idsegmento = :id_segment"
        ),
        {"value": value, "id_drug": id_drug, "id_segment": id_segment},
    )
    session_commit()


@pytest.fixture
def second_antimicrobial():
    """Flag drug 4 as antimicrobial on the adult segment"""
    _flag_antimicrobial(OTHER_DRUG, ADULT_SEGMENT, True)
    yield OTHER_DRUG
    _flag_antimicrobial(OTHER_DRUG, ADULT_SEGMENT, False)


@pytest.fixture
def cpoe_antimicrobial():
    """Flag the antimicrobial drug on the CPOE segment as well"""
    session.execute(
        text(
            "INSERT INTO demo.medatributos (fkmedicamento, idsegmento, antimicro) "
            "VALUES (:id_drug, :id_segment, true)"
        ),
        {"id_drug": ANTIMICROBIAL_DRUG, "id_segment": CPOE_SEGMENT},
    )
    session_commit()

    yield

    for table in ("medatributos_audit", "medatributos"):
        session.execute(
            text(
                f"DELETE FROM demo.{table} "
                "WHERE fkmedicamento = :id_drug AND idsegmento = :id_segment"
            ),
            {"id_drug": ANTIMICROBIAL_DRUG, "id_segment": CPOE_SEGMENT},
        )
    session_commit()


@pytest.fixture
def admin_utils_headers(client):
    """Headers with the ADMIN role (INTEGRATION_UTILS)"""
    return make_headers(get_access(client, roles=[Role.ADMIN.value]))


# ─── helpers ──────────────────────────────────────────────────────────────────


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
            dose=2.0,
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
                "validUntil": kwargs.get(
                    "valid_until", (datetime.now() + timedelta(days=7)).isoformat()
                ),
            }
            for id_drug in evaluations
        ],
    }
    response = client.post("/infection-control/review", json=payload, headers=headers)
    session_commit()
    return response


# ─── prescalc ─────────────────────────────────────────────────────────────────


def test_prescalc_without_feature_follows_nothing(admission):
    """A schema without the INFECTION_CONTROL feature is not followed"""
    _prescribe_today(admission, job=False)

    assert _record(admission) is None


def test_prescalc_without_antimicrobial_follows_nothing(infection_control, admission):
    """A prescription-day without antimicrobials does not follow the admission"""
    _prescribe_today(admission, drugs=(OTHER_DRUG,), job=False)

    assert _record(admission) is None


def test_prescalc_follows_admission(infection_control, admission):
    """An antimicrobial makes the admission pending and never reviewed; the
    reasons of its drugs are left to the job"""
    id_prescription = _prescribe_today(admission, job=False)

    record = _record(admission)
    assert record["tp_status"] == PENDING
    assert record["tp_origem"] == InfectionControlOriginEnum.PRESCALC.value
    # prescalc runs as the static (integration) user
    assert record["created_by"] == 0

    pendings = _open_pendings(admission)
    assert [p["tp_pendencia"] for p in pendings] == [NEVER_REVIEWED]
    assert pendings[0]["fkprescricao"] == id_prescription
    assert pendings[0]["tp_origem"] == InfectionControlOriginEnum.PRESCALC.value


def test_daily_prescriptions_keep_a_single_reason(infection_control, admission):
    """Prescalc on consecutive daily prescriptions opens 'never reviewed' once"""
    _prescalc(_prescribe(admission, _day(-1), _day(0)))
    _prescalc(_prescribe(admission, _day(0), _day(1)))

    pendings = _open_pendings(admission)
    assert [p["tp_pendencia"] for p in pendings] == [NEVER_REVIEWED]


def test_prescalc_leaves_reviewed_admission_alone(
    client, infection_controller_headers, infection_control, admission
):
    """A followed admission is the job's: prescalc doesn't reopen 'never
    reviewed' after a review"""
    _prescribe_today(admission)
    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    _prescribe_today(admission, job=False)

    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []


def test_atendcalc_follows_cpoe_admission(
    infection_control, cpoe_antimicrobial, admission
):
    """The CPOE path (atendcalc) follows the admission too"""
    _prescribe(admission, _day(-1), _day(2), id_segment=CPOE_SEGMENT)

    atendcalc({"schema": "demo", "admission_number": admission}, None)
    session_commit()

    record = _record(admission)
    assert record is not None
    assert record["tp_status"] == PENDING
    assert [p["tp_pendencia"] for p in _open_pendings(admission)] == [NEVER_REVIEWED]


def test_prescalc_reopens_closed_admission(infection_control, admission):
    """An antimicrobial restarted on a closed admission makes it pending again"""
    _suspend(_prescribe_today(admission))
    _run_job(admission)
    assert _record(admission)["tp_status"] == CLOSED

    _prescribe_today(admission, job=False)

    record = _record(admission)
    assert record["tp_status"] == PENDING
    # never reviewed: the reason is open again
    assert [p["tp_pendencia"] for p in _open_pendings(admission)] == [NEVER_REVIEWED]


def test_prescalc_reopens_reviewed_admission_for_the_job(
    client, infection_controller_headers, infection_control, admission
):
    """A reviewed admission reopened by prescalc waits for the job to open the
    reasons of its drugs"""
    id_prescription = _prescribe_today(admission)
    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )
    _suspend(id_prescription)
    _run_job(admission)
    assert _record(admission)["tp_status"] == CLOSED

    _prescribe_today(admission, job=False)

    assert _record(admission)["tp_status"] == PENDING
    assert _open_pendings(admission) == []

    _run_job(admission)

    assert [
        (p["tp_pendencia"], p["fkmedicamento"]) for p in _open_pendings(admission)
    ] == [(NO_EVALUATION, ANTIMICROBIAL_DRUG)]


def test_prescalc_does_not_reopen_discharged_admission(
    client, infection_controller_headers, infection_control, admission
):
    """Recalculating a discharged patient's prescription keeps the record closed"""
    id_prescription = _prescribe_today(admission)
    _review(client, infection_controller_headers, admission)
    _discharge(admission)
    _run_job(admission)
    assert _record(admission)["tp_status"] == CLOSED

    _prescalc(id_prescription)

    assert _record(admission)["tp_status"] == CLOSED
    assert _open_pendings(admission) == []


def test_prescalc_does_not_follow_discharged_admission(infection_control, admission):
    """A discharged patient is not followed"""
    _discharge(admission)

    _prescribe_today(admission, job=False)

    assert _record(admission) is None


# ─── rule (applied by the scheduled job) ──────────────────────────────────────


def test_rule_opens_reasons_of_each_drug(infection_control, admission):
    """The rule opens a reason for each running drug without an evaluation"""
    id_prescription = _prescribe_today(admission, job=False)

    _run_job(admission)

    pendings = _open_pendings(admission)
    assert [p["tp_pendencia"] for p in pendings] == [NEVER_REVIEWED, NO_EVALUATION]
    assert pendings[1]["fkmedicamento"] == ANTIMICROBIAL_DRUG
    assert pendings[1]["fkprescricao"] == id_prescription
    assert pendings[1]["tp_origem"] == InfectionControlOriginEnum.JOB.value
    assert _record(admission)["tp_status"] == PENDING


def test_new_antimicrobial_reopens_revised_admission(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    second_antimicrobial,
):
    """A new antimicrobial on a revised patient makes it pending again once
    the job runs"""
    _prescribe_today(admission)
    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )
    assert _record(admission)["tp_status"] == REVISED

    _prescribe_today(
        admission, drugs=(ANTIMICROBIAL_DRUG, second_antimicrobial), job=False
    )
    assert _record(admission)["tp_status"] == REVISED

    _run_job(admission)

    assert _record(admission)["tp_status"] == PENDING
    pendings = _open_pendings(admission)
    assert [(p["tp_pendencia"], p["fkmedicamento"]) for p in pendings] == [
        (NO_EVALUATION, second_antimicrobial)
    ]


def test_rule_closes_admission_when_drug_stops(infection_control, admission):
    """A suspended drug resolves its reasons and closes the admission"""
    _suspend(_prescribe_today(admission))

    _run_job(admission)

    assert _record(admission)["tp_status"] == CLOSED
    assert _open_pendings(admission) == []
    assert {p["tp_resolucao"] for p in _pendings(admission)} == {
        InfectionControlResolutionEnum.DRUG_NO_LONGER_ACTIVE.value
    }


def test_rule_closes_admission_on_discharge(
    client, infection_controller_headers, infection_control, admission
):
    """Discharge closes the admission, its evaluations and its reasons"""
    _prescribe_today(admission)
    _review(client, infection_controller_headers, admission)
    _discharge(admission)

    _run_job(admission)

    assert _record(admission)["tp_status"] == CLOSED
    assert {p["tp_resolucao"] for p in _pendings(admission) if p["tp_resolucao"]} >= {
        InfectionControlResolutionEnum.DISCHARGE.value
    }
    assert _open_pendings(admission) == []


# ─── review ───────────────────────────────────────────────────────────────────


def test_review_requires_permission(
    client, analyst_headers, infection_control, admission
):
    """401 without WRITE_INFECTION_CONTROL"""
    _prescribe_today(admission)

    response = _review(
        client, analyst_headers, admission, evaluations=[ANTIMICROBIAL_DRUG]
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_review_requires_token(client, infection_control, admission):
    """401 without a token"""
    response = client.post(
        "/infection-control/review", json={"admissionNumber": admission}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_review_requires_feature(client, infection_controller_headers, admission):
    """400 when the schema does not have the feature"""
    _prescribe_today(admission)

    response = _review(client, infection_controller_headers, admission)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"


def test_full_review_revises_admission(
    client, infection_controller_headers, infection_control, admission
):
    """Evaluating every running drug settles every reason"""
    _prescribe_today(admission)
    next_review = (datetime.now() + timedelta(days=3)).replace(microsecond=0)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        notes="Paciente estável",
        next_review_date=next_review.isoformat(),
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    data = response.get_json()["data"]
    assert data["status"] == REVISED
    assert data["pendings"] == []
    assert data["nextReviewDate"] == next_review.isoformat()
    assert data["reviews"][0]["notes"] == "Paciente estável"

    course = data["courses"][0]
    assert course["idDrug"] == ANTIMICROBIAL_DRUG
    assert course["ongoing"] is True
    assert course["evaluation"]["conforming"] is True
    assert course["evaluation"]["posology"]["dose"] == 2.0
    assert course["evaluation"]["posology"]["dailyFrequency"] is not None

    resolutions = {p["tp_pendencia"]: p["tp_resolucao"] for p in _pendings(admission)}
    assert resolutions == {
        NEVER_REVIEWED: InfectionControlResolutionEnum.REVIEW_SAVED.value,
        NO_EVALUATION: InfectionControlResolutionEnum.EVALUATED.value,
    }


def test_partial_review_keeps_admission_pending(
    client, infection_controller_headers, infection_control, admission
):
    """A review that evaluates nothing settles only 'never reviewed'"""
    _prescribe_today(admission)

    response = _review(client, infection_controller_headers, admission)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["status"] == PENDING
    assert [p["type"] for p in data["pendings"]] == [NO_EVALUATION]


def test_reevaluation_supersedes_previous(
    client, infection_controller_headers, infection_control, admission
):
    """Evaluating the same course again supersedes the evaluation in force"""
    _prescribe_today(admission)
    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )
    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    first, second = _evaluations(admission)
    assert first["tp_status"] == AntimicrobialEvaluationStatusEnum.SUPERSEDED.value
    assert (
        first["tp_encerramento"] == AntimicrobialEvaluationClosingEnum.SUPERSEDED.value
    )
    assert first["fkci_avaliacao_atm_substituta"] == second["idci_avaliacao_atm"]
    assert second["tp_status"] == AntimicrobialEvaluationStatusEnum.ACTIVE.value
    assert _record(admission)["tp_status"] == REVISED


def test_suspended_drug_is_settled_on_save(
    client, infection_controller_headers, infection_control, admission
):
    """A drug suspended before being evaluated stops keeping the patient pending"""
    _suspend(_prescribe_today(admission))

    response = _review(client, infection_controller_headers, admission)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["status"] == CLOSED
    no_evaluation = next(
        p for p in _pendings(admission) if p["tp_pendencia"] == NO_EVALUATION
    )
    assert (
        no_evaluation["tp_resolucao"]
        == InfectionControlResolutionEnum.DRUG_NO_LONGER_ACTIVE.value
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"valid_until": (datetime.now() - timedelta(hours=1)).isoformat()},
        {"next_review_date": (datetime.now() - timedelta(hours=1)).isoformat()},
    ],
)
def test_review_rejects_past_dates(
    client, infection_controller_headers, infection_control, admission, kwargs
):
    """Validity and the next review date must be in the future"""
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        **kwargs,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"


def test_review_rejects_drug_not_running(
    client, infection_controller_headers, infection_control, admission
):
    """Only running antimicrobials can be evaluated"""
    _prescribe_today(admission)

    response = _review(
        client, infection_controller_headers, admission, evaluations=[OTHER_DRUG]
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert _evaluations(admission) == []


# ─── state, worklist, backfill ────────────────────────────────────────────────


def test_state_without_feature(client, analyst_headers, admission):
    """The page learns the feature is off"""
    response = client.get(
        f"/infection-control/admission/{admission}", headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["enabled"] is False


def test_state_of_followed_admission(
    client, analyst_headers, infection_control, admission
):
    """Status, open reasons and the courses of a followed admission"""
    _prescribe_today(admission)

    response = client.get(
        f"/infection-control/admission/{admission}", headers=analyst_headers
    )

    data = response.get_json()["data"]
    assert data["followed"] is True
    assert data["status"] == PENDING
    assert [p["type"] for p in data["pendings"]] == [NEVER_REVIEWED, NO_EVALUATION]
    assert data["courses"][0]["evaluation"] is None


def test_worklist_lists_pending_admission(
    client, analyst_headers, infection_control, admission
):
    """The worklist brings the admission with its open reasons"""
    _prescribe_today(admission)

    response = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING], "limit": 500},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    rows = [
        a
        for a in response.get_json()["data"]["admissions"]
        if a["admissionNumber"] == admission
    ]
    assert len(rows) == 1
    assert rows[0]["idPatient"] == str(PATIENT_ID)
    assert [p["type"] for p in rows[0]["pendings"]] == [NEVER_REVIEWED, NO_EVALUATION]


def test_backfill_requires_integration_utils(
    client, analyst_headers, infection_control
):
    """401 without INTEGRATION_UTILS"""
    response = client.post(
        "/infection-control/backfill", json={}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_backfill_follows_admission_on_antimicrobial(
    client, admin_utils_headers, infection_control, admission
):
    """Admissions already on antimicrobials are followed without prescalc"""
    _prescribe(admission, _day(-1), _day(1))

    response = client.post(
        "/infection-control/backfill",
        json={"after": admission - 1, "limit": 200},
        headers=admin_utils_headers,
    )
    session_commit()

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    assert response.get_json()["data"]["created"] >= 1
    record = _record(admission)
    assert record["tp_origem"] == InfectionControlOriginEnum.BACKFILL.value
    assert record["tp_status"] == PENDING


def test_backfill_follows_open_ended_cpoe_order(
    client, admin_utils_headers, infection_control, cpoe_antimicrobial, admission
):
    """A CPOE order started days ago and still open is followed"""
    _prescribe(admission, _day(-5), None, id_segment=CPOE_SEGMENT)

    response = client.post(
        "/infection-control/backfill",
        json={"after": admission - 1, "limit": 200},
        headers=admin_utils_headers,
    )
    session_commit()

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    record = _record(admission)
    assert record is not None
    assert record["tp_origem"] == InfectionControlOriginEnum.BACKFILL.value


# ─── prescalc must not break ──────────────────────────────────────────────────


def _patient_day(admission_number):
    return session.execute(
        text(
            "SELECT fkprescricao FROM demo.prescricao "
            "WHERE nratendimento = :admission AND agregada = true"
        ),
        {"admission": admission_number},
    ).first()


def test_prescalc_survives_hook_failure(infection_control, admission, monkeypatch):
    """A failure in the infection control step does not stop the prescription-day"""

    def fail(*args, **kwargs):
        raise RuntimeError("infection control failure")

    monkeypatch.setattr(
        "repository.infection_control.infection_control_repository.create_admission",
        fail,
    )

    _prescribe_today(admission, job=False)

    assert _patient_day(admission) is not None
    assert _record(admission) is None


def test_prescalc_does_not_wait_for_a_review(
    infection_control, admission, second_antimicrobial
):
    """A review holding a followed record doesn't make prescalc wait: the
    record is the job's"""
    _prescribe_today(admission)

    id_prescription = _prescribe(
        admission, _day(-1), _day(1), drugs=(ANTIMICROBIAL_DRUG, second_antimicrobial)
    )

    # creating the prescription above commits the test session, so the lock is
    # taken only now
    _hold_record(admission)
    started = datetime.now()
    try:
        response = json.loads(
            prescalc(
                {"schema": "demo", "id_prescription": id_prescription, "force": True},
                None,
            )
        )
    finally:
        session_commit()

    assert response["status"] == "success", response
    assert datetime.now() - started < timedelta(seconds=2)
    assert _record(admission)["tp_status"] == PENDING
