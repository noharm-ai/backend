"""Tests: the rules that guard the outcome of an intervention
(POST /intervention/set-outcome ->
intervention_outcome_service.set_intervention_outcome).

Closing an intervention is what turns a pharmacist's note into money in the
consolidated economy report: the outcome decides whether the economy counts at
all, and the payload carries the figures it is counted from -- how much is
saved per day, for how many days, and from which prescription the count
starts. Those figures are never recomputed afterwards, so a payload the
endpoint lets through wrong is wrong in the report forever.

The endpoint therefore refuses more than it accepts, and what it refuses
depends on the economy the intervention's reason gave it:

* a *custom* economy has no prescription to derive figures from, so both the
  daily value and the number of days must be typed in by hand;
* a *substitution* closed without a substitute prescription has nothing to
  compare against, so it demands the same two figures manually;
* a substitution *with* a substitute re-bases the economy on the substitute's
  prescription date, because that is the day the cheaper drug started;
* any intervention carrying an economy needs a daily value before it can be
  closed, and an intervention reopened as pending ("s") has to give every one
  of those figures back.

The happy path of the endpoint is covered by test_intervention_outcome.py, and
how the base date is first stamped by test_intervention_economy_base_date.py.
These tests drive the rules around them.
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
OUTCOME_URL = "/intervention/set-outcome"

# seed reasons (demo.motivointervencao), one per economy kind
REASON_PLAIN = 5  # "Duplicidade medicamentosa" -- no economy
REASON_SUSPENSION = 22  # "Suspensão da terapia"
REASON_SUBSTITUTION = 23  # "Substituição"
REASON_CUSTOM_ECONOMY = 1  # "Alta antecipada"

# an id that is never created, to drive the "record is gone" branches
MISSING_ID = 999999

# the shape the frontend posts as the intervened item; only its truthiness and
# its round trip into intervencao.origem matter to these rules
ORIGIN = {
    "idDrug": 3,
    "name": "Medicamento de teste",
    "dose": "5.0",
    "frequencyDay": 2,
    "price": "4.52",
    "pricePerDose": "9.04",
}


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


def _prescription_with_drug(date=None):
    """Create a prescription with one drug and return (admission, prescription, drug)."""
    id_prescription = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1
    admission = test_counters["admission_number"]
    test_counters["admission_number"] += 1

    create_prescription(
        id=id_prescription,
        admissionNumber=admission,
        idPatient=1,
        date=date or datetime.now(),
        idDepartment=1,
    )

    id_prescription_drug = int(f"{id_prescription}001")
    create_prescription_drug(
        id=id_prescription_drug,
        idPrescription=id_prescription,
        idDrug=3,
    )

    return admission, id_prescription, id_prescription_drug


def _open_intervention(client, headers, reason=REASON_SUSPENSION, date=None):
    """Open a pending intervention on a fresh prescription drug.

    Returns (id_intervention, admission).
    """
    admission, _, id_prescription_drug = _prescription_with_drug(date=date)

    response = client.put(
        INTERVENTION_URL,
        json={
            "status": "s",
            "admissionNumber": admission,
            "idInterventionReason": [reason],
            "idPrescriptionDrug": str(id_prescription_drug),
        },
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK

    return response.get_json()["data"][0]["idIntervention"], admission


def _payload(id_intervention, **extra):
    """A body that satisfies every rule, for one field at a time to break."""
    body = {
        "idIntervention": id_intervention,
        "outcome": "a",
        "origin": ORIGIN,
        "destiny": None,
        "idPrescriptionDrugDestiny": None,
        "economyDayValue": 10.5,
        "economyDayValueManual": True,
        "economyDayAmount": 3,
        "economyDayAmountManual": True,
    }
    body.update(extra)

    return body


def _stored(id_intervention) -> Intervention:
    """Re-read the intervention the endpoint just wrote."""
    session.expire_all()

    return (
        session.query(Intervention)
        .filter(Intervention.idIntervention == id_intervention)
        .one()
    )


class TestRecordRules:
    """Teste post /intervention/set-outcome - registro alvo do desfecho"""

    def test_requires_write_permission(self, client, viewer_headers):
        """Perfil somente leitura não pode registrar desfecho"""
        response = client.post(
            OUTCOME_URL, json=_payload(MISSING_ID), headers=viewer_headers
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_rejects_an_unknown_intervention(self, client, analyst_headers):
        """Intervenção inexistente deve ser recusada"""
        response = client.post(
            OUTCOME_URL, json=_payload(MISSING_ID), headers=analyst_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.get_json()["code"] == "errors.invalidRecord"

    def test_rejects_an_intervention_whose_drug_was_archived(
        self, client, analyst_headers
    ):
        """Intervenção cujo medicamento saiu da base não pode ser alterada"""
        id_intervention, _ = _open_intervention(client, analyst_headers)

        # archiving moves the prescription drug out of demo.presmed; the
        # intervention keeps pointing at the id that is no longer there
        session.execute(
            text("UPDATE demo.intervencao SET fkpresmed = :gone WHERE idintervencao = :id"),
            {"gone": MISSING_ID, "id": id_intervention},
        )
        session_commit()

        response = client.post(
            OUTCOME_URL, json=_payload(id_intervention), headers=analyst_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "arquivada" in response.get_json()["message"]

    def test_rejects_an_intervention_whose_prescription_was_archived(
        self, client, analyst_headers
    ):
        """Intervenção de prescrição arquivada não pode ser alterada"""
        id_intervention, _ = _open_intervention(client, analyst_headers)

        # an intervention opened on a whole prescription carries fkpresmed = 0
        session.execute(
            text(
                "UPDATE demo.intervencao SET fkpresmed = 0, fkprescricao = :gone "
                "WHERE idintervencao = :id"
            ),
            {"gone": MISSING_ID, "id": id_intervention},
        )
        session_commit()

        response = client.post(
            OUTCOME_URL, json=_payload(id_intervention), headers=analyst_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "arquivada" in response.get_json()["message"]

    @pytest.mark.parametrize("outcome", ["z", "", "A", None])
    def test_rejects_an_outcome_outside_the_known_codes(
        self, client, analyst_headers, outcome
    ):
        """Somente os desfechos conhecidos são aceitos"""
        id_intervention, _ = _open_intervention(client, analyst_headers)

        response = client.post(
            OUTCOME_URL,
            json=_payload(id_intervention, outcome=outcome),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.get_json()["message"] == "Desfecho inválido"
        # nothing was written: the intervention is still pending
        assert _stored(id_intervention).status == "s"

    @pytest.mark.parametrize("outcome", ["a", "n", "x", "j", "s"])
    def test_accepts_every_known_outcome(self, client, analyst_headers, outcome):
        """Os cinco desfechos previstos são gravados"""
        id_intervention, _ = _open_intervention(client, analyst_headers)

        response = client.post(
            OUTCOME_URL,
            json=_payload(id_intervention, outcome=outcome),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert _stored(id_intervention).status == outcome


class TestManualEconomyFields:
    """Teste post /intervention/set-outcome - economia informada manualmente"""

    @pytest.mark.parametrize(
        "missing",
        [
            {"economyDayAmountManual": False},
            {"economyDayValueManual": False},
            {"economyDayAmountManual": False, "economyDayValueManual": False},
        ],
        ids=["amount", "value", "both"],
    )
    def test_custom_economy_demands_both_figures_by_hand(
        self, client, analyst_headers, missing
    ):
        """Economia customizada exige Economia/Dia e Qtd. de dias manuais"""
        id_intervention, _ = _open_intervention(
            client, analyst_headers, reason=REASON_CUSTOM_ECONOMY
        )
        assert (
            _stored(id_intervention).economy_type
            == InterventionEconomyTypeEnum.CUSTOM.value
        )

        response = client.post(
            OUTCOME_URL,
            json=_payload(id_intervention, **missing),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "customizada" in response.get_json()["message"]

    @pytest.mark.parametrize("amount", [None, 0])
    def test_a_manual_day_count_must_be_positive(
        self, client, analyst_headers, amount
    ):
        """Qtd. de dias manual deve ser informada e maior que zero"""
        id_intervention, _ = _open_intervention(client, analyst_headers)

        response = client.post(
            OUTCOME_URL,
            json=_payload(id_intervention, economyDayAmount=amount),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "maior que zero" in response.get_json()["message"]

    def test_a_manual_daily_value_must_be_informed(self, client, analyst_headers):
        """Economia/Dia manual sem valor deve ser recusada"""
        id_intervention, _ = _open_intervention(client, analyst_headers)

        response = client.post(
            OUTCOME_URL,
            json=_payload(id_intervention, economyDayValue=None),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.get_json()["message"] == "Economia/Dia inválido"

    def test_a_manual_daily_value_of_zero_is_accepted(self, client, analyst_headers):
        """Zero é um valor válido: a intervenção pode não ter gerado economia"""
        id_intervention, _ = _open_intervention(client, analyst_headers)

        response = client.post(
            OUTCOME_URL,
            json=_payload(id_intervention, economyDayValue=0),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert _stored(id_intervention).economy_day_value == 0

    def test_an_economy_needs_a_daily_value_even_when_not_manual(
        self, client, analyst_headers
    ):
        """Sem Economia/Dia calculado não há como fechar uma intervenção com economia"""
        id_intervention, _ = _open_intervention(client, analyst_headers)

        response = client.post(
            OUTCOME_URL,
            json=_payload(
                id_intervention,
                economyDayValue=None,
                economyDayValueManual=False,
                economyDayAmountManual=False,
            ),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.get_json()["message"] == "Economia/Dia inválido"

    def test_an_intervention_without_economy_ignores_the_figures(
        self, client, analyst_headers
    ):
        """Motivo sem economia fecha sem exigir valores"""
        id_intervention, _ = _open_intervention(
            client, analyst_headers, reason=REASON_PLAIN
        )
        assert _stored(id_intervention).economy_type is None

        response = client.post(
            OUTCOME_URL,
            json=_payload(
                id_intervention,
                economyDayValue=None,
                economyDayValueManual=False,
                economyDayAmountManual=False,
            ),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        stored = _stored(id_intervention)
        assert stored.status == "a"
        assert stored.economy_day_value is None


class TestSubstitutionWithoutDestiny:
    """Teste post /intervention/set-outcome - substituição sem prescrição destino"""

    def test_demands_a_manual_daily_value(self, client, analyst_headers):
        """Sem destino, Economia/Dia precisa ser informada manualmente"""
        id_intervention, _ = _open_intervention(
            client, analyst_headers, reason=REASON_SUBSTITUTION
        )
        assert (
            _stored(id_intervention).economy_type
            == InterventionEconomyTypeEnum.SUBSTITUTION.value
        )

        response = client.post(
            OUTCOME_URL,
            json=_payload(id_intervention, economyDayValueManual=False),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Economia/Dia deve ser especificado" in response.get_json()["message"]

    def test_demands_a_manual_day_count(self, client, analyst_headers):
        """Sem destino, a Qtd. de dias também precisa ser informada manualmente"""
        id_intervention, _ = _open_intervention(
            client, analyst_headers, reason=REASON_SUBSTITUTION
        )

        response = client.post(
            OUTCOME_URL,
            json=_payload(id_intervention, economyDayAmountManual=False),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Qtd. de dias" in response.get_json()["message"]

    def test_a_substitution_left_pending_needs_no_figures(
        self, client, analyst_headers
    ):
        """Reabrir como pendente não exige economia manual"""
        id_intervention, _ = _open_intervention(
            client, analyst_headers, reason=REASON_SUBSTITUTION
        )

        response = client.post(
            OUTCOME_URL,
            json=_payload(
                id_intervention,
                outcome="s",
                economyDayValue=None,
                economyDayValueManual=False,
                economyDayAmountManual=False,
            ),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK


class TestSubstitutionDestiny:
    """Teste post /intervention/set-outcome - substituição com prescrição destino"""

    def test_rejects_a_destiny_drug_without_a_prescription(
        self, client, analyst_headers
    ):
        """Medicamento destino órfão não define data base"""
        id_intervention, _ = _open_intervention(
            client, analyst_headers, reason=REASON_SUBSTITUTION
        )

        id_prescription = test_counters["id_prescription"]
        test_counters["id_prescription"] += 1
        orphan_drug = int(f"{id_prescription}001")
        create_prescription_drug(
            id=orphan_drug,
            idPrescription=MISSING_ID,
            idDrug=4,
        )

        response = client.post(
            OUTCOME_URL,
            json=_payload(id_intervention, idPrescriptionDrugDestiny=orphan_drug),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.get_json()["message"] == "Prescrição destino não encontrada"

    def test_rebases_the_economy_on_the_substitute_prescription(
        self, client, analyst_headers
    ):
        """A economia passa a contar da data da prescrição substituta"""
        id_intervention, _ = _open_intervention(
            client,
            analyst_headers,
            reason=REASON_SUBSTITUTION,
            date=datetime.now() - timedelta(days=10),
        )

        substitute_date = datetime.now() - timedelta(days=4)
        _, _, id_destiny_drug = _prescription_with_drug(date=substitute_date)

        response = client.post(
            OUTCOME_URL,
            json=_payload(
                id_intervention,
                idPrescriptionDrugDestiny=id_destiny_drug,
                economyDayAmount=5,
            ),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        stored = _stored(id_intervention)
        assert stored.idPrescriptionDrugDestiny == id_destiny_drug
        assert stored.date_base_economy.date() == substitute_date.date()
        # the manual day count is inclusive of the base date
        assert stored.economy_days == 5
        assert stored.date_end_economy.date() == (
            substitute_date + timedelta(days=4)
        ).date()

    def test_a_calculated_economy_needs_no_manual_figures(
        self, client, analyst_headers
    ):
        """Com destino informado, os valores calculados bastam"""
        id_intervention, _ = _open_intervention(
            client, analyst_headers, reason=REASON_SUBSTITUTION
        )
        _, _, id_destiny_drug = _prescription_with_drug()

        response = client.post(
            OUTCOME_URL,
            json=_payload(
                id_intervention,
                idPrescriptionDrugDestiny=id_destiny_drug,
                economyDayValueManual=False,
                economyDayAmountManual=False,
                economyDayAmount=None,
            ),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        stored = _stored(id_intervention)
        assert stored.economy_day_value_manual is False
        # left for the report to derive from the prescription period
        assert stored.economy_days is None
        assert stored.date_end_economy is None


class TestStoredOutcome:
    """Teste post /intervention/set-outcome - o que fica gravado"""

    def test_records_who_closed_the_intervention_and_when(
        self, client, analyst_headers
    ):
        """O desfecho registra responsável e data"""
        id_intervention, _ = _open_intervention(client, analyst_headers)

        response = client.post(
            OUTCOME_URL, json=_payload(id_intervention), headers=analyst_headers
        )

        assert response.status_code == status.HTTP_200_OK
        stored = _stored(id_intervention)
        assert stored.status == "a"
        assert stored.outcome_by is not None
        assert stored.outcome_at.date() == datetime.today().date()
        assert stored.economy_day_value == pytest.approx(10.5)
        assert stored.economy_day_value_manual is True
        assert stored.origin["idDrug"] == ORIGIN["idDrug"]

    def test_an_intervention_without_an_origin_saves_no_economy(
        self, client, analyst_headers
    ):
        """Sem item de origem não há economia a contabilizar"""
        id_intervention, _ = _open_intervention(client, analyst_headers)

        response = client.post(
            OUTCOME_URL,
            json=_payload(id_intervention, origin=None),
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        stored = _stored(id_intervention)
        # zeroed rather than left at the posted value, and flagged as manual so
        # no later recalculation puts money back into the report
        assert stored.economy_day_value == 0
        assert stored.economy_day_value_manual is True

    def test_reopening_as_pending_gives_every_figure_back(
        self, client, analyst_headers
    ):
        """Voltar a pendente limpa a economia gravada"""
        id_intervention, _ = _open_intervention(
            client, analyst_headers, reason=REASON_SUBSTITUTION
        )
        _, _, id_destiny_drug = _prescription_with_drug()

        closed = client.post(
            OUTCOME_URL,
            json=_payload(id_intervention, idPrescriptionDrugDestiny=id_destiny_drug),
            headers=analyst_headers,
        )
        assert closed.status_code == status.HTTP_200_OK
        assert _stored(id_intervention).economy_days == 3

        reopened = client.post(
            OUTCOME_URL,
            json=_payload(
                id_intervention,
                outcome="s",
                economyDayValue=None,
                economyDayValueManual=False,
                economyDayAmountManual=False,
            ),
            headers=analyst_headers,
        )

        assert reopened.status_code == status.HTTP_200_OK
        stored = _stored(id_intervention)
        assert stored.status == "s"
        assert stored.idPrescriptionDrugDestiny is None
        assert stored.economy_day_value is None
        assert stored.economy_day_value_manual is False
        assert stored.economy_days is None
        assert stored.date_end_economy is None
        assert stored.origin is None
        assert stored.destiny is None
