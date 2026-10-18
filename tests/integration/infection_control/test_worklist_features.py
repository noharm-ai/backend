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


def _drugs(features):
    """The drugs of the running courses kept on the record"""
    return sorted(course["idDrug"] for course in features["courses"])


def test_rule_keeps_running_antimicrobials(
    infection_control, admission, second_antimicrobial
):
    """The job keeps the running drugs on the record and drops a suspended one"""
    id_prescription = _prescribe_today(
        admission, drugs=(ANTIMICROBIAL_DRUG, OTHER_DRUG)
    )

    features = _record(admission)["indicadores"]
    assert _drugs(features) == [ANTIMICROBIAL_DRUG, OTHER_DRUG]
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

    assert _drugs(_record(admission)["indicadores"]) == [ANTIMICROBIAL_DRUG]


def _criteria(*criteria, match_all=False):
    """The antimicrobials filter: any criterion, or every one with match_all,
    met by a course of its own"""
    return {"antimicrobials": list(criteria), "antimicrobialsMatchAll": match_all}


def test_worklist_filters_by_antimicrobial(
    client, infection_controller_headers, infection_control, admission
):
    """Only admissions running any of the chosen antimicrobials; prescalc
    follows an admission without them, the job fills them in"""
    _prescribe_today(admission, job=False)

    def listed(*criteria):
        return _listed(
            client, infection_controller_headers, admission, **_criteria(*criteria)
        )

    assert listed({"idDrug": [ANTIMICROBIAL_DRUG]}) == []

    _run_job(admission)

    assert listed({"idDrug": [ANTIMICROBIAL_DRUG]}) == [admission]
    assert listed({"idDrug": [OTHER_DRUG, ANTIMICROBIAL_DRUG]}) == [admission]
    assert listed({"idDrug": [OTHER_DRUG]}) == []
    # an empty criterion asks for nothing
    assert listed({}) == [admission]


def test_worklist_filters_by_substance_and_aware_level(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    antimicrobial_substance,
):
    """The substance of a criterion, either it or its drugs; the AWaRe group
    of any running antimicrobial"""
    _prescribe_today(admission)

    def listed(*criteria, **filters):
        return _listed(
            client,
            infection_controller_headers,
            admission,
            **_criteria(*criteria),
            **filters,
        )

    assert listed({"idSubstance": [antimicrobial_substance]}) == [admission]
    assert listed({"idSubstance": [antimicrobial_substance + 1]}) == []
    # the drug is not running, its substance is
    assert listed(
        {"idDrug": [OTHER_DRUG], "idSubstance": [antimicrobial_substance]}
    ) == [admission]
    assert listed(awareLevels=[AWARE_RESERVE]) == [admission]
    assert listed(awareLevels=[1, 2]) == []


def test_worklist_filters_by_treatment_day(
    client, infection_controller_headers, infection_control, admission
):
    """Admissions with an antimicrobial on a treatment day of the range,
    counted as the timeline counts them (D1 is the first 24 hours)"""
    # started 4 days and 1 hour ago: on D5
    _prescribe(admission, datetime.now() - timedelta(days=4, hours=1), _day(1))
    _run_job(admission)

    def listed(**days):
        return _listed(
            client, infection_controller_headers, admission, **_criteria(days)
        )

    assert listed(treatmentDayFrom=5, treatmentDayTo=5) == [admission]
    assert listed(treatmentDayFrom=1) == [admission]
    assert listed(treatmentDayFrom=5) == [admission]
    assert listed(treatmentDayFrom=6) == []
    assert listed(treatmentDayTo=5) == [admission]
    assert listed(treatmentDayTo=4) == []
    assert listed(treatmentDayFrom=1, treatmentDayTo=1) == []


def _d(day):
    """A treatment day range of a single day"""
    return {"treatmentDayFrom": day, "treatmentDayTo": day}


def test_worklist_filters_by_antimicrobials_on_their_treatment_days(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    second_antimicrobial,
):
    """Each criterion is met by a course of its own: the drug and the day of a
    criterion go together. Any criterion will do, or every one with
    antimicrobialsMatchAll"""
    # on D5
    _prescribe(admission, datetime.now() - timedelta(days=4, hours=1), _day(1))
    # started an hour ago: on D1
    _prescribe(
        admission, datetime.now() - timedelta(hours=1), _day(1), drugs=(OTHER_DRUG,)
    )
    _run_job(admission)

    def listed(*criteria, match_all=False):
        return _listed(
            client,
            infection_controller_headers,
            admission,
            **_criteria(*criteria, match_all=match_all),
        )

    assert listed(_d(1)) == [admission]
    assert listed({"idDrug": [OTHER_DRUG], **_d(1)}) == [admission]
    assert listed({"idDrug": [ANTIMICROBIAL_DRUG], **_d(1)}) == []
    assert listed({"idDrug": [ANTIMICROBIAL_DRUG], **_d(5)}) == [admission]

    on_d5 = {"idDrug": [ANTIMICROBIAL_DRUG], **_d(5)}
    on_d1 = {"idDrug": [OTHER_DRUG], **_d(1)}
    not_on_d1 = {"idDrug": [ANTIMICROBIAL_DRUG], **_d(1)}
    not_on_d5 = {"idDrug": [OTHER_DRUG], **_d(5)}

    # any of them: one is enough
    assert listed(not_on_d1, on_d1) == [admission]
    assert listed(on_d5, not_on_d5) == [admission]
    assert listed(not_on_d1, not_on_d5) == []
    # an empty criterion does not make every admission match
    assert listed(not_on_d1, {}) == []

    # all of them: one on D5 and the other on D1
    assert listed(on_d5, on_d1, match_all=True) == [admission]
    assert listed(not_on_d1, on_d1, match_all=True) == []


def test_worklist_limits_the_antimicrobial_criteria(
    client, infection_controller_headers, infection_control
):
    """At most 10 criteria"""
    response = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING], "antimicrobials": [{}] * 11},
        headers=infection_controller_headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


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
