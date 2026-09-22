"""Tests: the economy base date of a single intervention
(PUT /intervention -> intervention_service.save_intervention).

When a pharmacist opens an intervention whose reason carries an economy --
suspension, substitution or custom economy -- the backend stamps the
intervention with the date the economy starts counting from. Every later
economy figure of the intervention is measured from that date, so getting it
wrong shifts money in the consolidated economy report.

Where the date comes from depends on how the prescription is organised:

* an ordinary (non CPOE) segment counts from the date of the prescription the
  drug belongs to, or from the prescription itself when the intervention was
  opened on a whole prescription instead of on one drug;
* a CPOE segment has no meaningful per-prescription date for a drug -- the
  prescribed items are regrouped by the aggregated prescription -- so it counts
  from the aggregated prescription sent in the request, and from the date the
  intervention was opened when the request carries none.

The reason itself decides whether there is an economy at all: a reason without
one leaves the date empty, and an intervention opened on a whole prescription
only keeps a custom economy.

The batch endpoint (idPrescriptionDrugList) is covered in
test_intervention_multiple.py; these tests drive the single intervention path.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import InterventionEconomyTypeEnum
from models.prescription import Intervention
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from utils import status

INTERVENTION_URL = "/intervention"

# seed reasons carrying each economy flag (demo.motivointervencao)
REASON_PLAIN = 5  # "Duplicidade medicamentosa" -- no economy
REASON_SUSPENSION = 22  # "Suspensão da terapia"
REASON_CUSTOM_ECONOMY = 1  # "Alta antecipada"

# seed departments: a prescription's segment is derived from its department by
# a database trigger, so the CPOE segment is reached through its own department
# (demo.segmentosetor: department 1 -> segment 1, department 3 -> segment 2 CPOE)
DEPARTMENT = 1
DEPARTMENT_CPOE = 3

# a prescription id that is never created, to drive the "not found" branches
MISSING_PRESCRIPTION = 999999


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


def _prescription_with_drug(date=None, cpoe=False):
    """Create a prescription with one drug and return (admission, prescription, drug)."""
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
        idDepartment=DEPARTMENT_CPOE if cpoe else DEPARTMENT,
    )

    id_prescription_drug = int(f"{id_prescription}001")
    create_prescription_drug(
        id=id_prescription_drug,
        idPrescription=id_prescription,
        idDrug=3,
    )

    return admission, id_prescription, id_prescription_drug


def _aggregate_prescription(admission, date):
    """Create the aggregated prescription a CPOE request points at."""
    id_prescription = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1

    create_prescription(
        id=id_prescription,
        admissionNumber=admission,
        idPatient=1,
        date=date,
        idDepartment=DEPARTMENT_CPOE,
        agg=True,
    )

    return id_prescription


def _payload(admission, reasons=None, **extra):
    """Build a single-intervention PUT /intervention body."""
    body = {
        "status": "s",
        "admissionNumber": admission,
        "idInterventionReason": reasons if reasons is not None else [REASON_SUSPENSION],
    }
    body.update(extra)

    return body


def _intervention(admission) -> Intervention:
    """The single intervention stored for an admission."""
    session.expire_all()

    return (
        session.query(Intervention)
        .filter(Intervention.admissionNumber == admission)
        .one()
    )


class TestOrdinarySegment:
    """Teste put /intervention - data base de economia em segmento comum"""

    def test_counts_from_the_prescription_of_the_drug(self, client, analyst_headers):
        """A data base deve ser a data da prescrição do medicamento"""
        prescription_date = datetime.now() - timedelta(days=3)
        admission, _, id_prescription_drug = _prescription_with_drug(
            date=prescription_date
        )

        response = client.put(
            INTERVENTION_URL,
            json=_payload(admission, idPrescriptionDrug=str(id_prescription_drug)),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        intervention = _intervention(admission)
        assert intervention.economy_type == InterventionEconomyTypeEnum.SUSPENSION.value
        assert intervention.date_base_economy.date() == prescription_date.date()

    def test_counts_from_the_prescription_itself_when_opened_on_one(
        self, client, analyst_headers
    ):
        """Intervenção aberta sobre a prescrição conta a partir da data dela"""
        prescription_date = datetime.now() - timedelta(days=5)
        admission, id_prescription, _ = _prescription_with_drug(date=prescription_date)

        response = client.put(
            INTERVENTION_URL,
            json=_payload(
                admission,
                reasons=[REASON_CUSTOM_ECONOMY],
                idPrescription=str(id_prescription),
                idPrescriptionDrug="0",
            ),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        intervention = _intervention(admission)
        assert intervention.economy_type == InterventionEconomyTypeEnum.CUSTOM.value
        assert intervention.date_base_economy.date() == prescription_date.date()

    def test_rejects_a_drug_whose_prescription_is_gone(self, client, analyst_headers):
        """Medicamento sem prescrição correspondente deve ser recusado"""
        admission, id_prescription, _ = _prescription_with_drug()

        orphan_drug = int(f"{id_prescription}999")
        create_prescription_drug(
            id=orphan_drug,
            idPrescription=MISSING_PRESCRIPTION,
            idDrug=3,
        )

        response = client.put(
            INTERVENTION_URL,
            json=_payload(admission, idPrescriptionDrug=str(orphan_drug)),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            session.query(Intervention)
            .filter(Intervention.admissionNumber == admission)
            .count()
            == 0
        )


class TestCpoeSegment:
    """Teste put /intervention - data base de economia em segmento CPOE"""

    def test_counts_from_the_aggregated_prescription(self, client, analyst_headers):
        """Com prescrição agregada informada, a data base é a data dela"""
        drug_prescription_date = datetime.now() - timedelta(days=6)
        aggregate_date = datetime.now() - timedelta(days=2)

        admission, _, id_prescription_drug = _prescription_with_drug(
            date=drug_prescription_date, cpoe=True
        )
        id_aggregate = _aggregate_prescription(admission, aggregate_date)

        response = client.put(
            INTERVENTION_URL,
            json=_payload(
                admission,
                idPrescriptionDrug=str(id_prescription_drug),
                aggIdPrescription=id_aggregate,
            ),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        intervention = _intervention(admission)
        assert intervention.date_base_economy.date() == aggregate_date.date()

    def test_counts_from_today_without_an_aggregated_prescription(
        self, client, analyst_headers
    ):
        """Sem prescrição agregada, a data base é a data de abertura da intervenção"""
        admission, _, id_prescription_drug = _prescription_with_drug(
            date=datetime.now() - timedelta(days=6), cpoe=True
        )

        response = client.put(
            INTERVENTION_URL,
            json=_payload(admission, idPrescriptionDrug=str(id_prescription_drug)),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        intervention = _intervention(admission)
        assert intervention.date_base_economy.date() == datetime.today().date()
        assert intervention.date_base_economy.date() == intervention.date.date()

    def test_rejects_an_unknown_aggregated_prescription(self, client, analyst_headers):
        """Prescrição agregada inexistente deve ser recusada"""
        admission, _, id_prescription_drug = _prescription_with_drug(cpoe=True)

        response = client.put(
            INTERVENTION_URL,
            json=_payload(
                admission,
                idPrescriptionDrug=str(id_prescription_drug),
                aggIdPrescription=MISSING_PRESCRIPTION,
            ),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            session.query(Intervention)
            .filter(Intervention.admissionNumber == admission)
            .count()
            == 0
        )


class TestWithoutEconomy:
    """Teste put /intervention - intervenções que não geram economia"""

    def test_a_reason_without_economy_leaves_the_date_empty(
        self, client, analyst_headers
    ):
        """Motivo sem economia não deve preencher a data base"""
        admission, _, id_prescription_drug = _prescription_with_drug()

        client.put(
            INTERVENTION_URL,
            json=_payload(
                admission,
                reasons=[REASON_PLAIN],
                idPrescriptionDrug=str(id_prescription_drug),
            ),
            headers=analyst_headers,
        )

        intervention = _intervention(admission)
        assert intervention.economy_type is None
        assert intervention.date_base_economy is None

    def test_a_prescription_intervention_keeps_only_a_custom_economy(
        self, client, analyst_headers
    ):
        """Intervenção sobre a prescrição descarta economia que não seja customizada"""
        admission, id_prescription, _ = _prescription_with_drug()

        client.put(
            INTERVENTION_URL,
            json=_payload(
                admission,
                reasons=[REASON_SUSPENSION],
                idPrescription=str(id_prescription),
                idPrescriptionDrug="0",
            ),
            headers=analyst_headers,
        )

        intervention = _intervention(admission)
        assert intervention.economy_type is None
        assert intervention.date_base_economy is None


class TestExistingIntervention:
    """Teste put /intervention - atualização de intervenção já existente"""

    def test_an_already_stamped_date_is_not_recalculated(self, client, analyst_headers):
        """Data base já gravada não deve ser recalculada na atualização"""
        prescription_date = datetime.now() - timedelta(days=4)
        admission, _, id_prescription_drug = _prescription_with_drug(
            date=prescription_date
        )
        stamped_date = datetime.now() - timedelta(days=30)

        client.put(
            INTERVENTION_URL,
            json=_payload(admission, idPrescriptionDrug=str(id_prescription_drug)),
            headers=analyst_headers,
        )
        created = _intervention(admission)
        session.execute(
            text(
                "UPDATE demo.intervencao SET dt_base_economia = :date "
                "WHERE idintervencao = :id"
            ),
            {"date": stamped_date, "id": created.idIntervention},
        )
        session_commit()

        response = client.put(
            INTERVENTION_URL,
            json=_payload(
                admission,
                idIntervention=created.idIntervention,
                idPrescriptionDrug=str(id_prescription_drug),
                observation="revisado",
            ),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        intervention = _intervention(admission)
        assert intervention.notes == "revisado"
        assert intervention.date_base_economy.date() == stamped_date.date()
