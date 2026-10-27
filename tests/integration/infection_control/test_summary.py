"""Tests: infection control follow-up, the summary the report reads
(ci_atendimento.resumo_acompanhamento), kept by the rule on every run and
written only when it changes"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import inspect, text

from models.enums import (
    CultureResultTypeEnum,
    InfectionControlOriginEnum,
    InfectionControlStatusEnum,
)
from models.infection_control import InfectionControlAdmission
from models.main import db, dbSession
from services.infection_control import (
    infection_control_status_service,
    infection_control_summary_service,
)
from tests.conftest import session, session_commit
from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    CLOSED,
    CPOE_SEGMENT,
    PATIENT_ID,
    PENDING,
    _day,
    _discharge,
    _evaluations,
    _prescribe,
    _prescribe_today,
    _record,
    _review,
    _suspend,
)
from utils import status
from utils.static_context import static_user_context

# dedicated ids so the rows never collide with seed data or other tests
FIRST_CULTURE = 900301
TEST_SUBSTANCE = 10301
MICROORGANISM = "Escherichia coli teste"


def _sync(admission_number, now=None, cultures=False):
    """Apply the rule to the admission at `now`, as the scheduled job does,
    refreshing the culture facts of the summary when asked"""
    with static_user_context("demo"):
        dbSession.setSchema("demo")
        admission = infection_control_status_service.sync_admission(
            admission_number=admission_number,
            origin=InfectionControlOriginEnum.JOB,
            user_id=0,
            now=now,
        )
        if cultures and admission is not None:
            infection_control_summary_service.refresh_cultures(
                admission=admission, schema="demo", now=now
            )
        db.session.commit()
        db.session.remove()
    session_commit()


def _summary(admission_number):
    record = _record(admission_number)
    return record["resumo_acompanhamento"] if record else None


@pytest.fixture
def culture():
    """A culture of the test patient collected yesterday, with an antibiogram
    naming a microorganism"""
    session.execute(
        text(
            "INSERT INTO demo.cultura_cabecalho "
            "(idculturacab, fkpessoa, fkexame, fkitemexame, nomeexame, nomematerial, "
            " dtcoleta, dtliberacao) "
            "VALUES (:id, :patient, :id, :id, 'HEMOCULTURA TESTE', 'SANGUE TESTE', "
            " :collected, :released)"
        ),
        {
            "id": FIRST_CULTURE,
            "patient": PATIENT_ID,
            "collected": _day(-1),
            "released": _day(0),
        },
    )
    session.execute(
        text(
            "INSERT INTO demo.cultura "
            "(fkexame, fkitemexame, fkmedicamento, nomemedicamento, "
            " nomemicroorganismo, resultado) "
            "VALUES (:id, :id, 1, 'AMPICILINA TESTE', :microorganism, 'R')"
        ),
        {"id": FIRST_CULTURE, "microorganism": MICROORGANISM},
    )
    session_commit()

    yield FIRST_CULTURE

    session.execute(
        text("DELETE FROM demo.cultura WHERE fkitemexame >= :first"),
        {"first": FIRST_CULTURE},
    )
    session.execute(
        text("DELETE FROM demo.cultura_cabecalho WHERE idculturacab >= :first"),
        {"first": FIRST_CULTURE},
    )
    session_commit()


@pytest.fixture
def antimicrobial_substance():
    """Give the antimicrobial drug a substance, as the culture summary keys
    resistance by substance"""
    original = session.execute(
        text("SELECT sctid FROM demo.medicamento WHERE fkmedicamento = :id"),
        {"id": ANTIMICROBIAL_DRUG},
    ).scalar()
    session.execute(
        text(
            "INSERT INTO public.substancia (sctid, nome) VALUES (:id, 'SUBSTANCIA TESTE')"
        ),
        {"id": TEST_SUBSTANCE},
    )
    session.execute(
        text("UPDATE demo.medicamento SET sctid = :sctid WHERE fkmedicamento = :id"),
        {"sctid": TEST_SUBSTANCE, "id": ANTIMICROBIAL_DRUG},
    )
    session_commit()

    yield TEST_SUBSTANCE

    session.execute(
        text("UPDATE demo.medicamento SET sctid = :sctid WHERE fkmedicamento = :id"),
        {"sctid": original, "id": ANTIMICROBIAL_DRUG},
    )
    session.execute(
        text("DELETE FROM public.substancia WHERE sctid = :id"),
        {"id": TEST_SUBSTANCE},
    )
    session_commit()


def test_summary_written_on_first_run(infection_control, admission):
    """The rule keeps the running course and the department of each day"""
    _prescribe_today(admission)

    summary = _summary(admission)

    assert summary["v"] == infection_control_summary_service.SUMMARY_VERSION
    assert summary["status"] == PENDING
    [course] = summary["courses"]
    assert course["n"] == 1
    assert course["idDrug"] == ANTIMICROBIAL_DRUG
    assert course["ongoing"] is True
    assert course["end"] is None
    assert course["endedBy"] is None
    assert course["coveredUntil"] == datetime.now().date().isoformat()
    assert course["start"] == _day(-1).isoformat()
    assert course["treatmentDays"] == 2
    assert [r["dose"] for r in course["regimens"]] == [2.0]
    assert summary["days"]
    assert summary["days"][-1]["idDepartment"] is not None
    assert "culture" not in summary


def test_summary_not_rewritten_without_changes(infection_control, admission):
    """Another run that sees the same courses leaves the summary as it was"""
    _prescribe_today(admission)
    first = _summary(admission)

    _sync(admission, now=datetime.now() + timedelta(minutes=30))

    assert _summary(admission)["savedAt"] == first["savedAt"]


def test_running_cpoe_course_not_rewritten_every_hour(
    infection_control, cpoe_antimicrobial, admission
):
    """An open-ended order runs until now on every run: the summary keeps it
    at day precision, so the next hourly run changes nothing"""
    _prescribe(admission, _day(-3), None, id_segment=CPOE_SEGMENT)
    now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    _sync(admission, now=now)
    first = _summary(admission)
    assert first["courses"][0]["ongoing"] is True
    assert first["courses"][0]["cpoe"] is True

    _sync(admission, now=now + timedelta(hours=1))

    assert _summary(admission)["savedAt"] == first["savedAt"]


def test_closing_fills_the_end_of_the_course(infection_control, admission):
    """A suspended drug ends its course and closes the summary"""
    _suspend(_prescribe_today(admission))

    _sync(admission)

    summary = _summary(admission)
    assert summary["status"] == CLOSED
    [course] = summary["courses"]
    assert course["ongoing"] is False
    assert course["endedBy"] == infection_control_summary_service.ENDED_SUSPENDED
    assert course["end"] is not None
    assert course["coveredUntil"] == course["end"][:10]


def test_discharge_ends_the_course(infection_control, admission):
    """A course running at discharge ends at the discharge"""
    _prescribe_today(admission)
    _discharge(admission)

    _sync(admission)

    [course] = _summary(admission)["courses"]
    assert course["endedBy"] == infection_control_summary_service.ENDED_DISCHARGE
    assert course["end"] <= datetime.now().isoformat()


def test_summary_lists_the_evaluations_of_each_course(
    client, infection_controller_headers, infection_control, admission
):
    """A saved review runs the rule: the summary names the evaluation of the
    course"""
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    [evaluation] = _evaluations(admission)
    summary = _summary(admission)
    assert summary["courses"][0]["idEvaluations"] == [evaluation["idci_avaliacao_atm"]]
    assert summary["status"] == InfectionControlStatusEnum.REVISED.value


def test_reopened_admission_rewrites_the_summary(infection_control, admission):
    """A closed admission whose antimicrobial restarts is followed again, and
    the summary follows it"""
    _suspend(_prescribe_today(admission))
    _sync(admission)
    assert _summary(admission)["status"] == CLOSED

    _prescribe_today(admission)

    summary = _summary(admission)
    assert summary["status"] == PENDING
    assert summary["courses"][-1]["ongoing"] is True


def test_summary_matches_the_timeline(
    client, infection_controller_headers, infection_control, admission
):
    """The courses of the summary are the timeline's"""
    _prescribe(admission, _day(-4), _day(-3))
    _prescribe_today(admission)

    response = client.get(
        f"/infection-control/antimicrobial-timeline/{admission}",
        headers=infection_controller_headers,
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    timeline = response.get_json()["data"]["courses"]
    summary = _summary(admission)["courses"]
    assert [c["start"] for c in summary] == [c["start"] for c in timeline]
    assert [c["idDrug"] for c in summary] == [c["idDrug"] for c in timeline]
    assert [len(c["gaps"]) for c in summary] == [len(c["gaps"]) for c in timeline]
    assert [[r["route"] for r in c["regimens"]] for c in summary] == [
        [r["route"] for r in c["regimens"]] for c in timeline
    ]


def test_cultures_refreshed_only_when_stale(infection_control, admission, culture):
    """The culture facts are read when missing and again only after
    CULTURE_REFRESH"""
    _prescribe_today(admission, job=False)
    now = datetime.now()
    _sync(admission, now=now, cultures=True)

    facts = _summary(admission)["culture"]
    assert facts["checkedAt"] == now.isoformat()
    assert facts["collected"] >= 1
    assert MICROORGANISM in facts["microorganisms"]
    assert facts["byCourse"]["1"]["collectedBefore"] is True
    assert facts["byCourse"]["1"]["collectedAt"] == _day(-1).isoformat()

    _sync(admission, now=now + timedelta(hours=1), cultures=True)
    assert _summary(admission)["culture"]["checkedAt"] == now.isoformat()

    later = now + infection_control_summary_service.CULTURE_REFRESH
    _sync(admission, now=later, cultures=True)
    assert _summary(admission)["culture"]["checkedAt"] == later.isoformat()


def test_resistant_release_while_running(
    monkeypatch, infection_control, antimicrobial_substance, admission
):
    """A resistant antibiogram of the course's substance released while it
    runs is kept on the course, read as the cultureResistant alert reads it"""
    released = _day(0)
    monkeypatch.setattr(
        infection_control_summary_service.feature_service,
        "has_feature",
        lambda feature: True,
    )
    monkeypatch.setattr(
        infection_control_summary_service.culture_service,
        "get_culture_summary",
        lambda schema, id_patient: [
            {
                "drug": "AMPICILINA TESTE",
                "sctid": antimicrobial_substance,
                "items": [
                    {
                        "result": "R",
                        "resultType": CultureResultTypeEnum.RESISTANT.value,
                        "releaseDate": released.isoformat(),
                    }
                ],
            }
        ],
    )
    _prescribe_today(admission, job=False)

    _sync(admission, cultures=True)

    summary = _summary(admission)
    assert summary["courses"][0]["idSubstance"] == antimicrobial_substance
    assert summary["culture"]["byCourse"]["1"]["resistantReleasedAt"] == [
        released.isoformat()
    ]


def test_summary_is_not_loaded_with_the_record(infection_control, admission):
    """The worklist loads records without the summary (deferred column)"""
    _prescribe_today(admission)

    with static_user_context("demo"):
        dbSession.setSchema("demo")
        record = (
            db.session.query(InfectionControlAdmission)
            .filter(InfectionControlAdmission.admission_number == admission)
            .first()
        )
        assert "summary" not in inspect(record).dict
        db.session.remove()


def test_backfill_summary_requires_integration_utils(
    client, analyst_headers, infection_control
):
    """401 without INTEGRATION_UTILS"""
    response = client.post(
        "/infection-control/backfill-summary", json={}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_backfill_summary_fills_closed_admission(
    client, admin_utils_headers, infection_control, admission
):
    """A closed admission without a summary (closed before it existed) gets
    one from its courses, with the culture facts"""
    _suspend(_prescribe_today(admission))
    _sync(admission)
    session.execute(
        text(
            "UPDATE demo.ci_atendimento SET resumo_acompanhamento = NULL "
            "WHERE nratendimento = :admission"
        ),
        {"admission": admission},
    )
    session_commit()

    response = client.post(
        "/infection-control/backfill-summary",
        json={"after": admission - 1, "limit": 200},
        headers=admin_utils_headers,
    )
    session_commit()

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    assert response.get_json()["data"]["filled"] >= 1
    summary = _summary(admission)
    assert summary["status"] == CLOSED
    assert summary["courses"][0]["ongoing"] is False
    assert "checkedAt" in summary["culture"]
    assert _record(admission)["tp_status"] == CLOSED
