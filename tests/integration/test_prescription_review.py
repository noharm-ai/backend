"""Tests: POST /prescriptions/review

Checking a prescription and *reviewing* a patient are two different acts. A
check is per prescription; a review is the pharmacist saying "I have looked at
this patient as a whole", so it is only offered on the aggregated prescription
that stands for the admission. The flag is a toggle -- it can be set and taken
back -- and every flip has to leave a trail, because the review counters in the
reports are built from that trail rather than from the flag itself.

That is what these tests pin down:

* the toggle persists, in both directions, and the response says which way it
  went and who did it;
* each flip appends a ``prescricao_audit`` row, REVISION on the way in and
  UNDO_REVISION on the way out, carrying the item count and the time the
  pharmacist spent on the screen;
* the three refusals that keep the trail honest -- an individual prescription
  cannot be reviewed, an unknown prescription is not invented, and a review
  status outside the enum is not stored;
* a caller who cannot write a prescription cannot review one either.
"""

import json
from datetime import datetime

import pytest
from sqlalchemy import text

from models.enums import (
    DrugTypeEnum,
    PrescriptionAuditTypeEnum,
    PrescriptionReviewTypeEnum,
)
from models.prescription import Prescription, PrescriptionAudit
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from utils import status

URL = "/prescriptions/review"

REVIEWED = PrescriptionReviewTypeEnum.REVIEWED.value
PENDING = PrescriptionReviewTypeEnum.PENDING.value

# the user behind every fixture in tests.conftest.get_access
CALLER_NAME = "Demonstração"

# above every id the test helpers hand out, so no run can make it exist
MISSING_PRESCRIPTION = 999999999


def _create_agg_prescription(drug_count: int = 2) -> int:
    """Write an aggregated prescription with `drug_count` drugs inside it.

    A review targets the aggregation, but the items it counts live on the
    individual prescriptions underneath, so both halves are written: the agg row
    that the endpoint is called with, and one internal prescription holding the
    drugs. Ids come from the shared >= 100000 counter, so tests.conftest cleans
    them up.
    """
    admission = test_counters["admission_number"]
    id_agg = test_counters["id_prescription"]
    id_internal = id_agg + 1

    test_counters["id_prescription"] += 2
    test_counters["admission_number"] += 1

    date = datetime.now()

    create_prescription(
        id=id_agg, admissionNumber=admission, idPatient=1, agg=True, date=date
    )
    create_prescription(
        id=id_internal, admissionNumber=admission, idPatient=1, date=date
    )

    for i in range(drug_count):
        create_prescription_drug(
            id=int(f"{id_internal}00{i + 1}"),
            idPrescription=id_internal,
            idDrug=3 + i,
        )

    return id_agg


def _audits(id_prescription: int) -> list[PrescriptionAudit]:
    """Every audit row written for a prescription, oldest first."""
    return (
        session.query(PrescriptionAudit)
        .filter(PrescriptionAudit.idPrescription == id_prescription)
        .order_by(PrescriptionAudit.id)
        .all()
    )


def _review_type(id_prescription: int):
    """The persisted review flag, read back outside the request session."""
    return (
        session.query(Prescription.reviewType)
        .filter(Prescription.id == id_prescription)
        .scalar()
    )


@pytest.fixture
def agg_prescription() -> int:
    """An aggregated prescription with two drugs, not yet reviewed."""
    return _create_agg_prescription()


def test_review_marks_the_prescription_as_reviewed(
    client, analyst_headers, agg_prescription
):
    """Teste post /prescriptions/review - Deve marcar a prescrição agregada como revisada"""
    response = client.post(
        URL,
        json={"idPrescription": agg_prescription, "reviewType": REVIEWED},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    assert data["reviewed"] is True
    assert data["reviewedBy"] == CALLER_NAME
    # a timestamp the frontend shows straight away, so it must parse
    assert datetime.fromisoformat(data["reviewedAt"])

    assert _review_type(agg_prescription) == REVIEWED


def test_undo_review_marks_the_prescription_as_pending(
    client, analyst_headers, agg_prescription
):
    """Teste post /prescriptions/review - Deve permitir desfazer a revisão"""
    client.post(
        URL,
        json={"idPrescription": agg_prescription, "reviewType": REVIEWED},
        headers=analyst_headers,
    )

    response = client.post(
        URL,
        json={"idPrescription": agg_prescription, "reviewType": PENDING},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["reviewed"] is False
    assert _review_type(agg_prescription) == PENDING


def test_review_writes_a_revision_audit(client, analyst_headers, agg_prescription):
    """Teste post /prescriptions/review - Deve registrar auditoria do tipo REVISION"""
    client.post(
        URL,
        json={"idPrescription": agg_prescription, "reviewType": REVIEWED},
        headers=analyst_headers,
    )

    audits = _audits(agg_prescription)
    assert len(audits) == 1

    audit = audits[0]
    assert audit.auditType == PrescriptionAuditTypeEnum.REVISION.value
    assert audit.agg is True
    assert audit.idPrescription == agg_prescription


def test_undo_review_writes_an_undo_revision_audit(
    client, analyst_headers, agg_prescription
):
    """Teste post /prescriptions/review - Desfazer a revisão registra auditoria UNDO_REVISION"""
    client.post(
        URL,
        json={"idPrescription": agg_prescription, "reviewType": REVIEWED},
        headers=analyst_headers,
    )
    client.post(
        URL,
        json={"idPrescription": agg_prescription, "reviewType": PENDING},
        headers=analyst_headers,
    )

    audit_types = [a.auditType for a in _audits(agg_prescription)]
    assert audit_types == [
        PrescriptionAuditTypeEnum.REVISION.value,
        PrescriptionAuditTypeEnum.UNDO_REVISION.value,
    ]


def test_review_audit_counts_the_items_inside_the_aggregation(client, analyst_headers):
    """Teste post /prescriptions/review - A auditoria conta os itens das prescrições agregadas"""
    id_agg = _create_agg_prescription(drug_count=3)

    client.post(
        URL,
        json={"idPrescription": id_agg, "reviewType": REVIEWED},
        headers=analyst_headers,
    )

    assert _audits(id_agg)[0].totalItens == 3


def test_review_audit_ignores_items_outside_the_counted_types(client, analyst_headers):
    """Teste post /prescriptions/review - A auditoria não conta itens do tipo Materiais"""
    id_agg = _create_agg_prescription(drug_count=2)
    id_internal = id_agg + 1

    # origem is rewritten by the insert trigger, so it is set with raw SQL
    session.execute(
        text("UPDATE demo.presmed SET origem = :source WHERE fkpresmed = :id"),
        {"source": DrugTypeEnum.MATERIAL.value, "id": int(f"{id_internal}001")},
    )
    session_commit()

    client.post(
        URL,
        json={"idPrescription": id_agg, "reviewType": REVIEWED},
        headers=analyst_headers,
    )

    assert _audits(id_agg)[0].totalItens == 1


def test_review_audit_records_the_reported_evaluation_time(
    client, analyst_headers, agg_prescription
):
    """Teste post /prescriptions/review - A auditoria registra o tempo de avaliação informado"""
    client.post(
        URL,
        json={
            "idPrescription": agg_prescription,
            "reviewType": REVIEWED,
            "evaluationTime": 42,
        },
        headers=analyst_headers,
    )

    assert _audits(agg_prescription)[0].extra["evaluationTime"] == 42


def test_review_audit_defaults_the_evaluation_time_to_zero(
    client, analyst_headers, agg_prescription
):
    """Teste post /prescriptions/review - Sem tempo de avaliação informado a auditoria registra zero"""
    client.post(
        URL,
        json={"idPrescription": agg_prescription, "reviewType": REVIEWED},
        headers=analyst_headers,
    )

    extra = _audits(agg_prescription)[0].extra
    assert extra["evaluationTime"] == 0
    # no evaluation was started on this prescription, so there is no start date
    assert extra["main_evaluationStartDate"] is None


def test_review_audit_carries_the_evaluation_start_date(client, analyst_headers):
    """Teste post /prescriptions/review - A auditoria copia a data de início da avaliação"""
    id_agg = _create_agg_prescription()
    start_date = "2024-01-02T03:04:05"

    session.execute(
        text(
            "UPDATE demo.prescricao SET indicadores = CAST(:features AS json) "
            "WHERE fkprescricao = :id"
        ),
        {
            "features": json.dumps({"evaluation": {"startDate": start_date}}),
            "id": id_agg,
        },
    )
    session_commit()

    client.post(
        URL,
        json={"idPrescription": id_agg, "reviewType": REVIEWED},
        headers=analyst_headers,
    )

    assert _audits(id_agg)[0].extra["main_evaluationStartDate"] == start_date


def test_review_rejects_an_individual_prescription(client, analyst_headers):
    """Teste post /prescriptions/review - Não deve revisar prescrição individual [400 BAD REQUEST]"""
    id_prescription = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1

    create_prescription(
        id=id_prescription,
        admissionNumber=test_counters["admission_number"],
        idPatient=1,
    )
    test_counters["admission_number"] += 1

    response = client.post(
        URL,
        json={"idPrescription": id_prescription, "reviewType": REVIEWED},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    # tp_revisao defaults to 0, so an untouched prescription reads back as pending
    assert _review_type(id_prescription) == PENDING
    assert _audits(id_prescription) == []


def test_review_rejects_a_missing_prescription(client, analyst_headers):
    """Teste post /prescriptions/review - Prescrição inexistente deve retornar erro [400 BAD REQUEST]"""
    response = client.post(
        URL,
        json={"idPrescription": MISSING_PRESCRIPTION, "reviewType": REVIEWED},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.parametrize("review_type", [2, -1, "reviewed", None])
def test_review_rejects_an_unknown_review_type(
    client, analyst_headers, agg_prescription, review_type
):
    """Teste post /prescriptions/review - Status de revisão fora do enum deve retornar erro [400 BAD REQUEST]"""
    response = client.post(
        URL,
        json={"idPrescription": agg_prescription, "reviewType": review_type},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert _review_type(agg_prescription) == PENDING
    assert _audits(agg_prescription) == []


def test_review_requires_write_permission(client, viewer_headers, agg_prescription):
    """Teste post /prescriptions/review - Usuário sem permissão de escrita deve receber [401 UNAUTHORIZED]"""
    response = client.post(
        URL,
        json={"idPrescription": agg_prescription, "reviewType": REVIEWED},
        headers=viewer_headers,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert _review_type(agg_prescription) == PENDING
    assert _audits(agg_prescription) == []
