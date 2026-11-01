"""Tests: segment authorization when closing an intervention
(POST /intervention/set-outcome ->
intervention_outcome_service._validate_authorization).

The demo schema runs with the AUTHORIZATION_SEGMENT feature on, so a
pharmacist may only record the outcome of an intervention whose segment they
are authorized on (demo user 1 is authorized on segments 1 and 2 only, see
public.usuario_autorizacao). The segment comes from a different record
depending on what the intervention was opened on:

* an intervention on a whole prescription (fkpresmed = 0) takes the segment of
  the prescription, and is refused when that prescription is gone;
* an intervention on a prescription drug takes the segment of the drug;
* an intervention recorded by an infection control review follows the
  admission, not the segment, so it is never checked;
* maintainers skip the check altogether.

The other rules of the endpoint are covered by
test_intervention_set_outcome_rules.py; these tests drive the authorization
alone, with a reason that carries no economy so nothing else gets in the way.
"""

from datetime import datetime

import pytest
from sqlalchemy import text

from models.prescription import Intervention
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from utils import status

INTERVENTION_URL = "/intervention"
OUTCOME_URL = "/intervention/set-outcome"

# seed reason with no economy ("Duplicidade medicamentosa")
REASON_PLAIN = 5

AUTHORIZED_SEGMENT = 1
UNAUTHORIZED_SEGMENT = 99

# an id that is never created, to drive the "record is gone" branch
MISSING_ID = 999999


@pytest.fixture
def maintainer_analyst_headers(client):
    """Headers of a pharmacist who is also a maintainer (ADMIN holds MAINTAINER
    but not WRITE_PRESCRIPTION)"""
    return make_headers(
        get_access(
            client,
            roles=[Role.PRESCRIPTION_ANALYST.value, Role.ADMIN.value],
        )
    )


@pytest.fixture(autouse=True)
def clean_interventions():
    """Drop the interventions this module writes -- tests.conftest does not know them."""
    yield
    session.execute(
        text(
            "DELETE FROM demo.intervencao_audit WHERE idintervencao IN "
            "(SELECT idintervencao FROM demo.intervencao WHERE nratendimento >= 100000)"
        )
    )
    session.execute(text("DELETE FROM demo.intervencao WHERE nratendimento >= 100000"))
    session_commit()


def _prescription_with_drug():
    """Create a prescription with one drug and return (admission, prescription, drug)."""
    id_prescription = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1
    admission = test_counters["admission_number"]
    test_counters["admission_number"] += 1

    create_prescription(
        id=id_prescription,
        admissionNumber=admission,
        idPatient=1,
        date=datetime.now(),
        idDepartment=1,
    )

    id_prescription_drug = int(f"{id_prescription}001")
    create_prescription_drug(
        id=id_prescription_drug,
        idPrescription=id_prescription,
        idDrug=3,
    )

    return admission, id_prescription, id_prescription_drug


def _open_on_prescription(client, headers):
    """Open a pending intervention on a whole prescription.

    Returns (id_intervention, id_prescription).
    """
    admission, id_prescription, _ = _prescription_with_drug()

    response = client.put(
        INTERVENTION_URL,
        json={
            "status": "s",
            "admissionNumber": admission,
            "idInterventionReason": [REASON_PLAIN],
            "idPrescription": str(id_prescription),
        },
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK

    return response.get_json()["data"][0]["idIntervention"], id_prescription


def _open_on_drug(client, headers):
    """Open a pending intervention on a prescription drug.

    Returns (id_intervention, id_prescription_drug).
    """
    admission, _, id_prescription_drug = _prescription_with_drug()

    response = client.put(
        INTERVENTION_URL,
        json={
            "status": "s",
            "admissionNumber": admission,
            "idInterventionReason": [REASON_PLAIN],
            "idPrescriptionDrug": str(id_prescription_drug),
        },
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK

    return response.get_json()["data"][0]["idIntervention"], id_prescription_drug


def _move_prescription(id_prescription, id_segment):
    """Move a prescription to another segment after it was created.

    Written with an UPDATE because the BEFORE INSERT trigger recomputes the
    segment from the department.
    """
    session.execute(
        text("UPDATE demo.prescricao SET idsegmento = :seg WHERE fkprescricao = :id"),
        {"seg": id_segment, "id": id_prescription},
    )
    session_commit()


def _move_drug(id_prescription_drug, id_segment):
    """Move a prescription drug to another segment after it was created."""
    session.execute(
        text("UPDATE demo.presmed SET idsegmento = :seg WHERE fkpresmed = :id"),
        {"seg": id_segment, "id": id_prescription_drug},
    )
    session_commit()


def _set_outcome(client, headers, id_intervention, outcome="a"):
    """Post an outcome that satisfies every other rule of the endpoint."""
    return client.post(
        OUTCOME_URL,
        json={
            "idIntervention": id_intervention,
            "outcome": outcome,
            "origin": None,
            "destiny": None,
            "idPrescriptionDrugDestiny": None,
            "economyDayValue": None,
            "economyDayValueManual": False,
            "economyDayAmount": None,
            "economyDayAmountManual": False,
        },
        headers=headers,
    )


def _stored_status(id_intervention) -> str:
    """Re-read the status the endpoint just wrote."""
    session.expire_all()

    return (
        session.query(Intervention.status)
        .filter(Intervention.idIntervention == id_intervention)
        .scalar()
    )


class TestPrescriptionIntervention:
    """Teste post /intervention/set-outcome - intervenção na prescrição inteira"""

    def test_authorized_segment_accepts_the_outcome(self, client, analyst_headers):
        """Prescrição em segmento autorizado deve aceitar o desfecho"""
        id_intervention, _ = _open_on_prescription(client, analyst_headers)

        response = _set_outcome(client, analyst_headers, id_intervention)

        assert response.status_code == status.HTTP_200_OK
        assert _stored_status(id_intervention) == "a"

    def test_unauthorized_segment_refuses_the_outcome(self, client, analyst_headers):
        """Prescrição em segmento não autorizado deve recusar o desfecho"""
        id_intervention, id_prescription = _open_on_prescription(
            client, analyst_headers
        )
        _move_prescription(id_prescription, UNAUTHORIZED_SEGMENT)

        response = _set_outcome(client, analyst_headers, id_intervention)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.get_json()["code"] == "errors.businessRules"
        assert "segmento" in response.get_json()["message"]
        assert _stored_status(id_intervention) == "s"

    def test_prescription_without_segment_is_not_checked(self, client, analyst_headers):
        """Prescrição sem segmento não é verificada"""
        id_intervention, id_prescription = _open_on_prescription(
            client, analyst_headers
        )
        _move_prescription(id_prescription, None)

        response = _set_outcome(client, analyst_headers, id_intervention)

        assert response.status_code == status.HTTP_200_OK
        assert _stored_status(id_intervention) == "a"

    def test_maintainer_skips_the_segment_check(
        self, client, analyst_headers, maintainer_analyst_headers
    ):
        """Mantenedor registra desfecho mesmo fora dos seus segmentos"""
        id_intervention, id_prescription = _open_on_prescription(
            client, analyst_headers
        )
        _move_prescription(id_prescription, UNAUTHORIZED_SEGMENT)

        response = _set_outcome(client, maintainer_analyst_headers, id_intervention)

        assert response.status_code == status.HTTP_200_OK
        assert _stored_status(id_intervention) == "a"


class TestPrescriptionDrugIntervention:
    """Teste post /intervention/set-outcome - intervenção no medicamento"""

    def test_authorized_segment_accepts_the_outcome(self, client, analyst_headers):
        """Medicamento em segmento autorizado deve aceitar o desfecho"""
        id_intervention, _ = _open_on_drug(client, analyst_headers)

        response = _set_outcome(client, analyst_headers, id_intervention)

        assert response.status_code == status.HTTP_200_OK
        assert _stored_status(id_intervention) == "a"

    def test_unauthorized_segment_refuses_the_outcome(self, client, analyst_headers):
        """Medicamento em segmento não autorizado deve recusar o desfecho"""
        id_intervention, id_prescription_drug = _open_on_drug(client, analyst_headers)
        _move_drug(id_prescription_drug, UNAUTHORIZED_SEGMENT)

        response = _set_outcome(client, analyst_headers, id_intervention)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.get_json()["code"] == "errors.businessRules"
        assert "segmento" in response.get_json()["message"]
        assert _stored_status(id_intervention) == "s"

    def test_refusal_is_by_the_drug_segment_not_the_prescription(
        self, client, analyst_headers
    ):
        """O segmento verificado é o do medicamento, não o da prescrição"""
        id_intervention, id_prescription_drug = _open_on_drug(client, analyst_headers)
        id_prescription = int(str(id_prescription_drug)[:-3])
        _move_prescription(id_prescription, UNAUTHORIZED_SEGMENT)

        response = _set_outcome(client, analyst_headers, id_intervention)

        assert response.status_code == status.HTTP_200_OK
        assert _stored_status(id_intervention) == "a"


class TestInfectionControlIntervention:
    """Teste post /intervention/set-outcome - intervenção do controle de infecção"""

    def test_infection_control_intervention_ignores_the_segment(
        self, client, analyst_headers, infection_controller_headers
    ):
        """Intervenção do controle de infecção segue o atendimento, não o segmento"""
        id_intervention, id_prescription_drug = _open_on_drug(client, analyst_headers)
        _move_drug(id_prescription_drug, UNAUTHORIZED_SEGMENT)
        session.execute(
            text(
                "UPDATE demo.intervencao SET fkci_avaliacao_atm = :ev "
                "WHERE idintervencao = :id"
            ),
            {"ev": MISSING_ID, "id": id_intervention},
        )
        session_commit()

        response = _set_outcome(client, infection_controller_headers, id_intervention)

        assert response.status_code == status.HTTP_200_OK
        assert _stored_status(id_intervention) == "a"
