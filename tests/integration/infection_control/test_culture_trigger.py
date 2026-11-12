"""Tests: infection control culture trigger (culture_trigger_service)

A review may turn the culture trigger on per drug evaluation (CULTURE_RESULT
among its triggers); the job opens a CULTURE_RESULT reason of the drug when a
culture result of the patient is released after the evaluation (in the
DynamoDB culture summary, faked here as the culture cache job of
backend-private fills it), and a new evaluation settles it without reopening
it on the same culture.
"""

from datetime import datetime, timedelta

import pytest

from models.enums import InfectionControlPendingTypeEnum
from repository import culture_repository
from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    EXPIRED,
    PATIENT_ID,
    PENDING,
    REVISED,
    _evaluations,
    _open_pendings,
    _pendings,
    _prescribe_today,
    _record,
    _review,
    _run_job,
)
from utils import status

CULTURE_RESULT = InfectionControlPendingTypeEnum.CULTURE_RESULT.value

# the culture summary of each patient, as the culture cache job feeds it
_summary: dict[int, list[dict]] = {}
_reads: list[tuple[str, int]] = []


@pytest.fixture(autouse=True)
def culture_summary(monkeypatch):
    """The DynamoDB culture summary, empty at the start of each test (tests
    never call AWS)"""
    _summary.clear()
    _reads.clear()

    def fake_summary(schema, id_patient):
        _reads.append((schema, id_patient))
        return list(_summary.get(id_patient, []))

    monkeypatch.setattr(
        culture_repository, "get_culture_summary_from_dynamodb", fake_summary
    )
    yield
    _summary.clear()


def _culture(release_date, result="Resistente", drug="AMICACINA", **kwargs):
    """A culture item of the test patient, as the culture cache job writes it"""
    _summary.setdefault(PATIENT_ID, []).append(
        {
            "schema_fkpessoa": f"demo:{PATIENT_ID}",
            "chave": f"URINA#E. COLI#{drug}",
            "ativo": kwargs.get("active", True),
            "nomemedicamento": drug,
            "nomematerial": "URINA",
            "microorganismo": "E. COLI",
            "resultado": result,
            "datacoleta": (release_date - timedelta(days=2)).isoformat(),
            "dataliberacao": release_date.isoformat(),
        }
    )


def _reviewed(client, headers, admission_number, triggers):
    """Reviews the antimicrobial with these optional triggers"""
    response = _review(
        client,
        headers,
        admission_number,
        evaluations=[ANTIMICROBIAL_DRUG],
        triggers=list(triggers),
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    return response.get_json()["data"]


def test_review_keeps_the_trigger(
    client, infection_controller_headers, infection_control, admission
):
    """The review accepts it among the optional triggers"""
    _prescribe_today(admission)
    _reviewed(client, infection_controller_headers, admission, [CULTURE_RESULT])

    (evaluation,) = _evaluations(admission)
    assert evaluation["gatilhos"] == [CULTURE_RESULT]


def test_a_new_culture_sends_the_patient_back_to_pending(
    client, infection_controller_headers, infection_control, admission
):
    """A culture released after the review opens a reason of the drug; a new
    evaluation settles it and the same culture doesn't reopen it"""
    _prescribe_today(admission)
    # seen by the reviewer
    _culture(datetime.now() - timedelta(days=1), drug="CEFTRIAXONA")
    _reviewed(client, infection_controller_headers, admission, [CULTURE_RESULT])

    _run_job(admission)
    assert _record(admission)["tp_status"] == REVISED

    # released after the review (the job runs after it), but a prediction is
    # not a result
    _culture(datetime.now(), result=None, drug="MEROPENEM")
    _run_job(admission)
    assert _record(admission)["tp_status"] == REVISED

    released = datetime.now()
    _culture(released)
    _run_job(admission)

    assert _record(admission)["tp_status"] == PENDING
    (pending,) = _open_pendings(admission)
    assert pending["tp_pendencia"] == CULTURE_RESULT
    assert pending["fkmedicamento"] == ANTIMICROBIAL_DRUG
    assert (
        pending["fkci_avaliacao_atm"]
        == _evaluations(admission)[0]["idci_avaliacao_atm"]
    )
    assert pending["detalhes"]["releaseDate"] == released.isoformat()
    assert pending["detalhes"]["cultures"] == [
        {
            "material": "URINA",
            "microorganism": "E. COLI",
            "releaseDate": released.isoformat(),
        }
    ]

    # the job running again keeps one reason
    _run_job(admission)
    assert len(_open_pendings(admission)) == 1

    data = _reviewed(client, infection_controller_headers, admission, [CULTURE_RESULT])
    assert data["status"] == REVISED

    _run_job(admission)
    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []
    assert [p["tp_pendencia"] for p in _pendings(admission)].count(CULTURE_RESULT) == 1


def test_an_evaluation_not_watching_cultures_ignores_them(
    client, infection_controller_headers, infection_control, admission
):
    """Without the trigger the summary isn't even read"""
    _prescribe_today(admission)
    _reviewed(client, infection_controller_headers, admission, [EXPIRED])

    _culture(datetime.now())
    _run_job(admission)

    assert _record(admission)["tp_status"] == REVISED
    assert _reads == []
