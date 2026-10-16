"""Tests: infection control follow-up, the reasons of a non-conformity and the
intervention a review may record with them, kept by infection control"""

from datetime import timedelta

import pytest
from sqlalchemy import text

from models.enums import (
    AntimicrobialEvaluationClosingEnum,
    InterventionAuditEnum,
    InterventionEconomyTypeEnum,
)
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    DEPARTMENT_BY_SEGMENT,
    ADULT_SEGMENT,
    _day,
    _evaluations,
    _prescribe_today,
    _review,
)
from utils import status

# synthetic reasons; the seed data flags none for infection control
REASON_IC = 30100
REASON_IC_SUSPENSION = 30101
REASON_NOT_IC = 30102
REASON_IC_INACTIVE = 30103
REASON_PARENT = 30104


@pytest.fixture
def reasons():
    """Intervention reasons for the review, one of them under a parent"""
    rows = [
        (REASON_PARENT, "ZZTEST Antimicrobiano", 0, True, False, True),
        (REASON_IC, "ZZTEST Espectro", REASON_PARENT, True, False, True),
        (REASON_IC_SUSPENSION, "ZZTEST Suspender", 0, True, True, True),
        (REASON_NOT_IC, "ZZTEST Diluição", 0, True, False, False),
        (REASON_IC_INACTIVE, "ZZTEST Inativo", 0, False, False, True),
    ]
    for id_reason, name, parent, active, suspension, infection_control in rows:
        session.execute(
            text(
                "INSERT INTO demo.motivointervencao "
                "(idmotivointervencao, nome, idmotivomae, ativo, suspensao, "
                "controle_infeccao) "
                "VALUES (:id, :name, :parent, :active, :suspension, :ic)"
            ),
            {
                "id": id_reason,
                "name": name,
                "parent": parent,
                "active": active,
                "suspension": suspension,
                "ic": infection_control,
            },
        )
    session_commit()

    yield

    session.execute(
        text(
            "DELETE FROM demo.motivointervencao "
            "WHERE idmotivointervencao BETWEEN 30100 AND 30199"
        )
    )
    session_commit()


@pytest.fixture
def interventions(admission):
    """Drop the interventions written for the admission"""
    yield
    session.execute(
        text(
            "DELETE FROM demo.intervencao_audit WHERE idintervencao IN "
            "(SELECT idintervencao FROM demo.intervencao WHERE nratendimento = :a)"
        ),
        {"a": admission},
    )
    session.execute(
        text("DELETE FROM demo.intervencao WHERE nratendimento = :a"),
        {"a": admission},
    )
    session_commit()


def _as(client, role: Role):
    """Headers of the demo user with only this role. Roles are read on each
    request, so they are set right before the call that uses them."""
    return make_headers(get_access(client, roles=[role.value]))


def _interventions(admission_number):
    return (
        session.execute(
            text(
                "SELECT * FROM demo.intervencao WHERE nratendimento = :admission "
                "ORDER BY idintervencao"
            ),
            {"admission": admission_number},
        )
        .mappings()
        .all()
    )


def _audits(id_intervention):
    return (
        session.execute(
            text("SELECT * FROM demo.intervencao_audit WHERE idintervencao = :id"),
            {"id": id_intervention},
        )
        .mappings()
        .all()
    )


def _non_conformity(client, admission, **kwargs):
    """A review judging the antimicrobial not conforming"""
    return _review(
        client,
        _as(client, Role.INFECTION_CONTROLLER),
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        conforming=False,
        evaluation_notes=kwargs.pop("evaluation_notes", "Espectro amplo"),
        **kwargs,
    )


def _ic_intervention(client, admission) -> str:
    """Record a non-conformity with an intervention; return its id"""
    _prescribe_today(admission)
    response = _non_conformity(
        client, admission, intervention_reasons=[REASON_IC], create_intervention=True
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()

    return str(_interventions(admission)[0]["idintervencao"])


def _outcome(id_intervention):
    return {
        "idIntervention": id_intervention,
        "outcome": "a",
        "origin": None,
        "destiny": None,
        "idPrescriptionDrugDestiny": None,
        "economyDayValue": None,
        "economyDayValueManual": False,
        "economyDayAmount": None,
        "economyDayAmountManual": False,
    }


def test_non_conformity_keeps_reasons_without_intervention(
    client, infection_control, admission, reasons, interventions
):
    """The reasons are recorded on the evaluation; no intervention unless asked"""
    _prescribe_today(admission)

    response = _non_conformity(
        client, admission, intervention_reasons=[REASON_IC_SUSPENSION, REASON_IC]
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    (evaluation,) = _evaluations(admission)
    assert evaluation["conforme"] is False
    assert evaluation["idmotivointervencao"] == [REASON_IC, REASON_IC_SUSPENSION]
    assert _interventions(admission) == []

    served = response.get_json()["data"]["courses"][0]["evaluation"]
    assert served["interventionReasons"] == [
        {"id": REASON_IC, "name": "ZZTEST Antimicrobiano - ZZTEST Espectro"},
        {"id": REASON_IC_SUSPENSION, "name": "ZZTEST Suspender"},
    ]
    assert served["interventions"] == []


def test_non_conformity_records_intervention(
    client, infection_control, admission, reasons, interventions
):
    """The intervention lands on the evaluated drug, pending, with the reasons
    and the justification, linked to the evaluation and audited"""
    id_prescription = _prescribe_today(admission)

    response = _non_conformity(
        client,
        admission,
        intervention_reasons=[REASON_IC],
        create_intervention=True,
        evaluation_notes="Descalonar conforme cultura",
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    (evaluation,) = _evaluations(admission)
    (intervention,) = _interventions(admission)
    assert intervention["fkpresmed"] == evaluation["fkpresmed"]
    assert intervention["fkpresmed"] == int(f"{id_prescription}001")
    assert intervention["fkprescricao"] == 0
    assert intervention["fkci_avaliacao_atm"] == evaluation["idci_avaliacao_atm"]
    assert intervention["idmotivointervencao"] == [REASON_IC]
    assert intervention["observacao"] == "Descalonar conforme cultura"
    assert intervention["status"] == "s"
    assert intervention["fksetor"] == DEPARTMENT_BY_SEGMENT[ADULT_SEGMENT]
    assert intervention["tp_economia"] is None

    (audit,) = _audits(intervention["idintervencao"])
    assert audit["tp_audit"] == InterventionAuditEnum.CREATE.value

    served = response.get_json()["data"]["courses"][0]["evaluation"]
    assert served["interventions"] == [
        {"id": str(intervention["idintervencao"]), "status": "s"}
    ]


def test_intervention_economy_follows_the_reasons(
    client, infection_control, admission, reasons, interventions
):
    """The economy comes from the reasons, as in the prescription screening"""
    _prescribe_today(admission)

    response = _non_conformity(
        client,
        admission,
        intervention_reasons=[REASON_IC_SUSPENSION],
        create_intervention=True,
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    (intervention,) = _interventions(admission)
    assert intervention["tp_economia"] == InterventionEconomyTypeEnum.SUSPENSION.value
    # the date of the prescription of the drug
    assert intervention["dt_base_economia"].date() == _day(-1).date()


def test_non_conformity_requires_reason(
    client, infection_control, admission, reasons, interventions
):
    """400 for a non-conformity without reasons"""
    _prescribe_today(admission)

    response = _non_conformity(client, admission)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"
    assert _evaluations(admission) == []


@pytest.mark.parametrize(
    "extra",
    [
        {"intervention_reasons": [REASON_IC]},
        {"create_intervention": True},
    ],
)
def test_conforming_takes_no_reason(
    client, infection_control, admission, reasons, interventions, extra
):
    """400 for reasons or an intervention on a conforming evaluation"""
    _prescribe_today(admission)

    response = _review(
        client,
        _as(client, Role.INFECTION_CONTROLLER),
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        **extra,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert _evaluations(admission) == []


@pytest.mark.parametrize("id_reason", [REASON_NOT_IC, REASON_IC_INACTIVE, 30199])
def test_reason_must_be_active_and_for_infection_control(
    client, infection_control, admission, reasons, interventions, id_reason
):
    """400 for a reason not flagged for infection control, inactive or unknown"""
    _prescribe_today(admission)

    response = _non_conformity(
        client,
        admission,
        intervention_reasons=[REASON_IC, id_reason],
        create_intervention=True,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"
    assert _evaluations(admission) == []
    assert _interventions(admission) == []


def test_retroactive_non_conformity_records_no_intervention(
    client, infection_control, admission, reasons, interventions
):
    """400 for an intervention on a record of the past: it would land on the
    drug prescribed now"""
    _prescribe_today(admission)
    _review(
        client,
        _as(client, Role.INFECTION_CONTROLLER),
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    # over before the evaluation in force started
    payload = {
        "valid_from": _day(-1).isoformat(),
        "valid_until": (_day(-1) + timedelta(hours=2)).isoformat(),
        "intervention_reasons": [REASON_IC],
    }
    response = _non_conformity(client, admission, create_intervention=True, **payload)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert len(_evaluations(admission)) == 1

    # without the intervention it is kept as history
    response = _non_conformity(client, admission, **payload)

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    retroactive = _evaluations(admission)[-1]
    assert (
        retroactive["tp_encerramento"]
        == AntimicrobialEvaluationClosingEnum.RETROACTIVE.value
    )
    assert _interventions(admission) == []


def test_pharmacist_cannot_change_infection_control_intervention(
    client, infection_control, admission, reasons, interventions
):
    """401 to edit or close an intervention kept by infection control"""
    id_intervention = _ic_intervention(client, admission)

    response = client.put(
        "/intervention",
        json={"idIntervention": id_intervention, "observation": "outra"},
        headers=_as(client, Role.PRESCRIPTION_ANALYST),
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    response = client.post(
        "/intervention/set-outcome",
        json=_outcome(id_intervention),
        headers=_as(client, Role.PRESCRIPTION_ANALYST),
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    (intervention,) = _interventions(admission)
    assert intervention["observacao"] == "Espectro amplo"
    assert intervention["status"] == "s"


def test_infection_control_changes_its_intervention(
    client, infection_control, admission, reasons, interventions
):
    """The infection control user edits and closes the intervention"""
    id_intervention = _ic_intervention(client, admission)

    response = client.put(
        "/intervention",
        json={
            "idIntervention": id_intervention,
            "idPrescriptionDrug": str(_interventions(admission)[0]["fkpresmed"]),
            "observation": "Ajustado com a equipe",
        },
        headers=_as(client, Role.INFECTION_CONTROLLER),
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    (served,) = response.get_json()["data"]
    assert served["idInfectionControlEvaluation"] == str(
        _evaluations(admission)[0]["idci_avaliacao_atm"]
    )

    response = client.post(
        "/intervention/set-outcome",
        json=_outcome(id_intervention),
        headers=_as(client, Role.INFECTION_CONTROLLER),
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()

    (intervention,) = _interventions(admission)
    assert intervention["observacao"] == "Ajustado com a equipe"
    assert intervention["status"] == "a"


def test_infection_control_cannot_change_screening_interventions(
    client, infection_control, admission, reasons, interventions
):
    """401 for the infection control user to create or edit an intervention
    of the prescription screening"""
    id_prescription = _prescribe_today(admission)
    id_prescription_drug = f"{id_prescription}001"
    payload = {
        "status": "s",
        "admissionNumber": admission,
        "idInterventionReason": [REASON_NOT_IC],
        "idPrescriptionDrug": id_prescription_drug,
        "observation": "triagem",
    }

    response = client.put(
        "/intervention", json=payload, headers=_as(client, Role.INFECTION_CONTROLLER)
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    response = client.put(
        "/intervention", json=payload, headers=_as(client, Role.PRESCRIPTION_ANALYST)
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    (served,) = response.get_json()["data"]
    assert served["idInfectionControlEvaluation"] is None
    session_commit()

    response = client.put(
        "/intervention",
        json={**payload, "idIntervention": served["idIntervention"]},
        headers=_as(client, Role.INFECTION_CONTROLLER),
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    response = client.post(
        "/intervention/set-outcome",
        json=_outcome(served["idIntervention"]),
        headers=_as(client, Role.INFECTION_CONTROLLER),
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_reasons_list_flags_infection_control(client, reasons):
    """The reasons served to the forms say which serve infection control"""
    response = client.get(
        "/intervention/reasons", headers=_as(client, Role.INFECTION_CONTROLLER)
    )

    assert response.status_code == status.HTTP_200_OK
    flags = {r["id"]: r["infectionControl"] for r in response.get_json()["data"]}
    assert flags[REASON_IC] is True
    assert flags[REASON_NOT_IC] is False
    assert REASON_IC_INACTIVE not in flags


@pytest.mark.parametrize(
    "role, locked",
    [(Role.PRESCRIPTION_ANALYST, True), (Role.INFECTION_CONTROLLER, False)],
)
def test_outcome_data_tells_who_can_change_it(
    client, infection_control, admission, reasons, interventions, role, locked
):
    """The outcome form is locked for whoever cannot change the intervention"""
    id_intervention = _ic_intervention(client, admission)

    response = client.get(
        f"/intervention/outcome-data?idIntervention={id_intervention}",
        headers=_as(client, role),
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    header = response.get_json()["data"]["header"]
    assert header["infectionControl"] is True
    assert header["locked"] is locked


def test_undone_intervention_leaves_the_evaluation(
    client, infection_control, admission, reasons, interventions
):
    """An intervention undone (status 0) is no longer listed on its
    evaluation, as the screening hides it"""
    id_intervention = _ic_intervention(client, admission)

    response = client.put(
        "/intervention",
        json={"idIntervention": id_intervention, "status": "0"},
        headers=_as(client, Role.INFECTION_CONTROLLER),
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    session_commit()

    response = client.get(
        f"/infection-control/admission/{admission}",
        headers=_as(client, Role.INFECTION_CONTROLLER),
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    evaluation = response.get_json()["data"]["courses"][0]["evaluation"]
    assert evaluation["interventions"] == []
    assert [r["id"] for r in evaluation["interventionReasons"]] == [REASON_IC]
