"""Tests: PUT /intervention with idPrescriptionDrugList (batch interventions).

``PUT /intervention`` serves two different code paths. With a single
``idPrescriptionDrug`` it goes to ``intervention_service.save_intervention``,
which creates or updates one intervention and is covered in test_intervention.py.
With a non-empty ``idPrescriptionDrugList`` it goes instead to
``intervention_service.add_multiple_interventions``, which creates one brand new
intervention per prescribed drug in a single request -- what the pharmacist
screen calls when several drugs are flagged for the same reason at once.

The batch path is not a loop over the single path: it derives the economy type,
the department and the RAM payload once for the whole request and applies them
to every intervention it creates, and it never updates an existing record.

What these tests pin down:

* one intervention per prescribed drug, each pointing at its own presmed row,
  carrying the shared admission number, reason list, error/cost flags and
  observation, opened with status "s" and no prescription of its own;
* the response carries exactly the interventions that were created;
* the department is copied from the admission's most recent prescription;
* the economy type follows the reason -- suspension, substitution and custom
  economy each map to their own type, an ordinary reason to none -- and the
  economy base date is filled in only when there is an economy type, from the
  prescription the drug belongs to;
* the RAM payload is stored only when a reason is flagged as RAM;
* every created intervention gets a CREATE audit row recording the economy type;
* a caller without WRITE_PRESCRIPTION writes nothing.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import InterventionAuditEnum, InterventionEconomyTypeEnum
from models.prescription import Intervention, InterventionAudit
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from utils import status

INTERVENTION_URL = "/intervention"

# the demo user, who authenticates every request in this module
AUTHOR_ID = 1

# seed reasons carrying each economy flag (demo.motivointervencao)
REASON_PLAIN = 5  # "Duplicidade medicamentosa" -- no economy
REASON_SUSPENSION = 22  # "Suspensão da terapia"
REASON_SUBSTITUTION = 23  # "Substituição"
REASON_CUSTOM_ECONOMY = 1  # "Alta antecipada"

# reserved id for the RAM reason this module creates; no seed reason has ram on
REASON_RAM = 90001

SEGMENT = 1  # the demo user is authorized on it (public.usuario_autorizacao)
DEPARTMENT = 7


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
    session.execute(
        text("DELETE FROM demo.motivointervencao WHERE idmotivointervencao >= 90000")
    )
    session_commit()


@pytest.fixture
def ram_reason():
    """A reason flagged as RAM -- the seed data has none."""
    session.execute(
        text(
            "INSERT INTO demo.motivointervencao "
            "(idmotivointervencao, nome, ativo, ram) VALUES (:id, 'ZZTEST RAM', true, true)"
        ),
        {"id": REASON_RAM},
    )
    session_commit()

    return REASON_RAM


def _prescription_with_drugs(drug_count=2, date=None, id_department=DEPARTMENT):
    """Create a prescription for a fresh admission and return (admission, date, drug ids)."""
    id_prescription = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1
    admission = test_counters["admission_number"]
    test_counters["admission_number"] += 1

    prescription_date = date or datetime.now()

    create_prescription(
        id=id_prescription,
        admissionNumber=admission,
        idPatient=1,
        date=prescription_date,
        idSegment=SEGMENT,
        idDepartment=id_department,
    )

    id_prescription_drugs = []
    for position in range(drug_count):
        id_prescription_drug = int(f"{id_prescription}{position + 1:03d}")
        create_prescription_drug(
            id=id_prescription_drug,
            idPrescription=id_prescription,
            idDrug=3 + position,
            idSegment=SEGMENT,
        )
        id_prescription_drugs.append(id_prescription_drug)

    return admission, prescription_date, id_prescription_drugs


def _payload(admission, id_prescription_drugs, reasons, **extra):
    """Build a batch PUT /intervention body."""
    body = {
        "idPrescriptionDrugList": [str(i) for i in id_prescription_drugs],
        "admissionNumber": admission,
        "idInterventionReason": reasons,
    }
    body.update(extra)

    return body


def _interventions(admission) -> list:
    """Every intervention stored for an admission, oldest id first."""
    session.expire_all()
    return (
        session.query(Intervention)
        .filter(Intervention.admissionNumber == admission)
        .order_by(Intervention.idIntervention)
        .all()
    )


def test_creates_one_intervention_per_prescribed_drug(client, analyst_headers):
    """Teste put /intervention - Deve criar uma intervenção para cada medicamento da lista"""
    admission, _, drugs = _prescription_with_drugs(drug_count=3)

    response = client.put(
        INTERVENTION_URL,
        json=_payload(admission, drugs, [REASON_PLAIN]),
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_200_OK

    interventions = _interventions(admission)
    assert len(interventions) == 3
    assert sorted(i.id for i in interventions) == sorted(drugs)


def test_created_interventions_carry_the_request_data(client, analyst_headers):
    """Teste put /intervention - As intervenções criadas devem gravar motivo, erro, custo e observação enviados"""
    admission, _, drugs = _prescription_with_drugs()

    client.put(
        INTERVENTION_URL,
        json=_payload(
            admission,
            drugs,
            [REASON_PLAIN],
            error=True,
            cost=True,
            observation="dose acima do previsto",
        ),
        headers=analyst_headers,
    )

    for intervention in _interventions(admission):
        assert intervention.admissionNumber == admission
        assert intervention.idInterventionReason == [REASON_PLAIN]
        assert intervention.error is True
        assert intervention.cost is True
        assert intervention.notes == "dose acima do previsto"
        assert intervention.user == AUTHOR_ID
        # a batch intervention always hangs off a presmed, never a prescription
        assert intervention.idPrescription == 0
        assert intervention.status == "s"
        assert intervention.date.date() == datetime.today().date()


def test_response_lists_the_created_interventions(client, analyst_headers):
    """Teste put /intervention - A resposta deve trazer exatamente as intervenções criadas"""
    admission, _, drugs = _prescription_with_drugs()

    response = client.put(
        INTERVENTION_URL,
        json=_payload(admission, drugs, [REASON_PLAIN]),
        headers=analyst_headers,
    )

    data = response.get_json()["data"]
    created = {str(i.idIntervention) for i in _interventions(admission)}

    assert {str(item["idIntervention"]) for item in data} == created


def test_department_comes_from_the_most_recent_prescription(client, analyst_headers):
    """Teste put /intervention - O setor deve vir da prescrição mais recente do atendimento"""
    admission, _, drugs = _prescription_with_drugs(id_department=DEPARTMENT)

    # a newer prescription on the same admission, in another department
    newer_department = 8
    id_newer = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1
    create_prescription(
        id=id_newer,
        admissionNumber=admission,
        idPatient=1,
        date=datetime.now() + timedelta(hours=1),
        idSegment=SEGMENT,
        idDepartment=newer_department,
    )

    client.put(
        INTERVENTION_URL,
        json=_payload(admission, drugs, [REASON_PLAIN]),
        headers=analyst_headers,
    )

    for intervention in _interventions(admission):
        assert intervention.idDepartment == newer_department


@pytest.mark.parametrize(
    "reason,economy_type",
    [
        (REASON_SUSPENSION, InterventionEconomyTypeEnum.SUSPENSION.value),
        (REASON_SUBSTITUTION, InterventionEconomyTypeEnum.SUBSTITUTION.value),
        (REASON_CUSTOM_ECONOMY, InterventionEconomyTypeEnum.CUSTOM.value),
    ],
)
def test_economy_type_follows_the_reason(client, analyst_headers, reason, economy_type):
    """Teste put /intervention - O tipo de economia deve ser derivado do motivo enviado"""
    admission, _, drugs = _prescription_with_drugs()

    client.put(
        INTERVENTION_URL,
        json=_payload(admission, drugs, [reason]),
        headers=analyst_headers,
    )

    for intervention in _interventions(admission):
        assert intervention.economy_type == economy_type


def test_an_ordinary_reason_has_no_economy_type(client, analyst_headers):
    """Teste put /intervention - Um motivo sem economia não deve gerar tipo nem data base de economia"""
    admission, _, drugs = _prescription_with_drugs()

    client.put(
        INTERVENTION_URL,
        json=_payload(admission, drugs, [REASON_PLAIN]),
        headers=analyst_headers,
    )

    for intervention in _interventions(admission):
        assert intervention.economy_type is None
        assert intervention.date_base_economy is None


def test_economy_base_date_comes_from_the_drugs_prescription(client, analyst_headers):
    """Teste put /intervention - A data base de economia deve ser a data da prescrição do medicamento"""
    prescription_date = datetime.now() - timedelta(days=2)
    admission, _, drugs = _prescription_with_drugs(date=prescription_date)

    client.put(
        INTERVENTION_URL,
        json=_payload(admission, drugs, [REASON_SUSPENSION]),
        headers=analyst_headers,
    )

    for intervention in _interventions(admission):
        assert intervention.date_base_economy.date() == prescription_date.date()


def test_ram_is_stored_only_for_a_ram_reason(client, analyst_headers, ram_reason):
    """Teste put /intervention - O ramData deve ser gravado quando o motivo é marcado como RAM"""
    admission, _, drugs = _prescription_with_drugs()
    ram_data = {"severity": "grave", "causality": "provavel"}

    client.put(
        INTERVENTION_URL,
        json=_payload(admission, drugs, [ram_reason], ramData=ram_data),
        headers=analyst_headers,
    )

    for intervention in _interventions(admission):
        assert intervention.ram == ram_data


def test_ram_is_dropped_when_no_reason_is_flagged_as_ram(client, analyst_headers):
    """Teste put /intervention - O ramData deve ser ignorado quando nenhum motivo é RAM"""
    admission, _, drugs = _prescription_with_drugs()

    client.put(
        INTERVENTION_URL,
        json=_payload(admission, drugs, [REASON_PLAIN], ramData={"severity": "grave"}),
        headers=analyst_headers,
    )

    for intervention in _interventions(admission):
        assert intervention.ram is None


def test_every_created_intervention_is_audited(client, analyst_headers):
    """Teste put /intervention - Cada intervenção criada deve gerar um registro de auditoria CREATE"""
    admission, _, drugs = _prescription_with_drugs()

    client.put(
        INTERVENTION_URL,
        json=_payload(admission, drugs, [REASON_SUSPENSION]),
        headers=analyst_headers,
    )

    created = [i.idIntervention for i in _interventions(admission)]
    audits = (
        session.query(InterventionAudit)
        .filter(InterventionAudit.idIntervention.in_(created))
        .all()
    )

    assert len(audits) == len(created)
    for audit in audits:
        assert audit.auditType == InterventionAuditEnum.CREATE.value
        assert audit.createdBy == AUTHOR_ID
        assert audit.extra["status"] == "s"
        assert audit.extra["update_responsible"] is False
        assert (
            audit.extra["economy_type"] == InterventionEconomyTypeEnum.SUSPENSION.value
        )


def test_batch_requires_write_prescription(client, viewer_headers):
    """Teste put /intervention - Deve retornar erro [401 UNAUTHORIZED] para usuário sem WRITE_PRESCRIPTION"""
    admission, _, drugs = _prescription_with_drugs()

    response = client.put(
        INTERVENTION_URL,
        json=_payload(admission, drugs, [REASON_PLAIN]),
        headers=viewer_headers,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert _interventions(admission) == []
