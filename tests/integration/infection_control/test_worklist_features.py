"""Tests: infection control worklist filters kept on the record by the rule

The rule (job, review save, manual follow, backfill) keeps on ci_atendimento
what it saw running (indicadores): the worklist filters by antimicrobial,
substance, AWaRe level, treatment days and non-conformity from it, without
joining the prescriptions of every admission.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    OTHER_DRUG,
    PENDING,
    REVISED,
    _day,
    _prescribe,
    _prescribe_today,
    _record,
    _review,
    _run_job,
)
from utils import status

SUBSTANCE = 9070001
AWARE_RESERVE = 3
REASON_NON_CONFORMING = 30150


@pytest.fixture
def antimicrobial_substance():
    """Give the antimicrobial drug a substance of the Reserve AWaRe group"""
    session.execute(
        text(
            "INSERT INTO public.substancia (sctid, nome, ativo, tp_nivel_atb) "
            "VALUES (:sctid, 'ZZTEST SUBSTANCIA ATM', true, :level)"
        ),
        {"sctid": SUBSTANCE, "level": AWARE_RESERVE},
    )
    session.execute(
        text("UPDATE demo.medicamento SET sctid = :sctid WHERE fkmedicamento = :id"),
        {"sctid": SUBSTANCE, "id": ANTIMICROBIAL_DRUG},
    )
    session_commit()

    yield SUBSTANCE

    session.execute(
        text("UPDATE demo.medicamento SET sctid = NULL WHERE fkmedicamento = :id"),
        {"id": ANTIMICROBIAL_DRUG},
    )
    session.execute(
        text("DELETE FROM public.substancia WHERE sctid = :sctid"),
        {"sctid": SUBSTANCE},
    )
    session_commit()


@pytest.fixture
def non_conforming_reason():
    """An active intervention reason flagged for infection control"""
    session.execute(
        text(
            "INSERT INTO demo.motivointervencao "
            "(idmotivointervencao, nome, idmotivomae, ativo, suspensao, "
            "substituicao, tp_relacao, controle_infeccao) "
            "VALUES (:id, 'ZZTEST Espectro amplo', 0, true, false, false, 0, true)"
        ),
        {"id": REASON_NON_CONFORMING},
    )
    session_commit()

    yield REASON_NON_CONFORMING

    session.execute(
        text("DELETE FROM demo.motivointervencao WHERE idmotivointervencao = :id"),
        {"id": REASON_NON_CONFORMING},
    )
    session_commit()


def _listed(client, headers, admission, statuses=(PENDING,), **filters):
    """Admission numbers of the worklist narrowed to one admission"""
    response = client.post(
        "/infection-control/admissions",
        json={
            "status": list(statuses),
            "admissionNumbers": [admission],
            **filters,
        },
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    return [a["admissionNumber"] for a in response.get_json()["data"]["admissions"]]


def test_rule_keeps_running_antimicrobials(
    infection_control, admission, second_antimicrobial
):
    """The job keeps the running drugs on the record and drops a suspended one"""
    id_prescription = _prescribe_today(
        admission, drugs=(ANTIMICROBIAL_DRUG, OTHER_DRUG)
    )

    features = _record(admission)["indicadores"]
    assert features["drugIDs"] == [ANTIMICROBIAL_DRUG, OTHER_DRUG]
    assert features["nonConforming"] is False

    session.execute(
        text(
            "UPDATE demo.presmed SET dtsuspensao = :date "
            "WHERE fkprescricao = :id AND fkmedicamento = :id_drug"
        ),
        {
            "date": datetime.now() - timedelta(hours=1),
            "id": id_prescription,
            "id_drug": OTHER_DRUG,
        },
    )
    session_commit()
    _run_job(admission)

    assert _record(admission)["indicadores"]["drugIDs"] == [ANTIMICROBIAL_DRUG]


def test_worklist_filters_by_antimicrobial(
    client, infection_controller_headers, infection_control, admission
):
    """Only admissions running any of the chosen antimicrobials; prescalc
    follows an admission without them, the job fills them in"""
    _prescribe_today(admission, job=False)

    def listed(**filters):
        return _listed(client, infection_controller_headers, admission, **filters)

    assert listed(idDrug=[ANTIMICROBIAL_DRUG]) == []

    _run_job(admission)

    assert listed(idDrug=[ANTIMICROBIAL_DRUG]) == [admission]
    assert listed(idDrug=[OTHER_DRUG, ANTIMICROBIAL_DRUG]) == [admission]
    assert listed(idDrug=[OTHER_DRUG]) == []


def test_worklist_filters_by_substance_and_aware_level(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    antimicrobial_substance,
):
    """The substance and the AWaRe group of the running antimicrobials"""
    _prescribe_today(admission)

    def listed(**filters):
        return _listed(client, infection_controller_headers, admission, **filters)

    assert listed(idSubstance=[antimicrobial_substance]) == [admission]
    assert listed(idSubstance=[antimicrobial_substance + 1]) == []
    assert listed(awareLevels=[AWARE_RESERVE]) == [admission]
    assert listed(awareLevels=[1, 2]) == []


def test_worklist_filters_by_treatment_days(
    client, infection_controller_headers, infection_control, admission
):
    """Admissions with an antimicrobial running for at least that many days,
    counted as the timeline counts them (D1 is the first 24 hours)"""
    # started 4 days and 1 hour ago: on D5
    _prescribe(admission, datetime.now() - timedelta(days=4, hours=1), _day(1))
    _run_job(admission)

    def listed(**filters):
        return _listed(client, infection_controller_headers, admission, **filters)

    assert listed(minTreatmentDays=1) == [admission]
    assert listed(minTreatmentDays=5) == [admission]
    assert listed(minTreatmentDays=6) == []


def test_worklist_filters_by_non_conformity(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    non_conforming_reason,
):
    """The review save keeps on the record that an evaluation in force is non
    conforming"""
    _prescribe_today(admission)

    def listed(statuses):
        return _listed(
            client,
            infection_controller_headers,
            admission,
            statuses=statuses,
            nonConforming=True,
        )

    assert listed([PENDING]) == []

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        conforming=False,
        intervention_reasons=[non_conforming_reason],
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()

    assert listed([REVISED]) == [admission]

    # judged conforming in a later review
    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()

    assert listed([REVISED]) == []
