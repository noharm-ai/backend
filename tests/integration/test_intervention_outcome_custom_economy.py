"""Integration tests for the custom-economy branch of GET /intervention/outcome-data
(``intervention_outcome_service.get_outcome_data``).

Most interventions derive their economy from the prescription itself: the
service reads the intervened item, prices it, and shows the pharmacist what
suspending or substituting it is worth per day. A *custom* economy has no such
item to read -- the reason ("Alta antecipada" and friends) saves money that no
drug price can express -- so the endpoint short-circuits and hands the screen a
simpler payload: the stored daily value, both figures flagged as typed in by
hand, and a single ``origin`` block pointing at the prescription the count
starts from.

``test_intervention_outcome.py`` drives the substitution flow and
``test_intervention_set_outcome_rules.py`` drives the rules that *close* a
custom-economy intervention, but the screen that opens it was never exercised.
These tests cover it on both records it can be opened from:

* an intervention on a prescription *drug*, where ``idPrescription`` is 0 and
  the prescription is reached through the intervened item;
* an intervention on the *prescription*, which carries no item at all --
  ``save_intervention`` only lets a prescription-level intervention keep a
  custom economy, every other kind is dropped.
"""

from datetime import datetime

import pytest
from sqlalchemy import text

from models.enums import InterventionEconomyTypeEnum
from models.prescription import Intervention
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from utils import prescriptionutils, status

INTERVENTION_URL = "/intervention"
OUTCOME_DATA_URL = "/intervention/outcome-data"
SET_OUTCOME_URL = "/intervention/set-outcome"

# seed reasons (demo.motivointervencao)
REASON_CUSTOM_ECONOMY = 1  # "Alta antecipada" -- economia customizada
REASON_SUSPENSION = 22  # "Suspensão da terapia"

REASON_CUSTOM_LABEL = "Alta antecipada"

SEGMENT = 1
DEPARTMENT = 1
DRUG = 3

MISSING_ID = 999999

# the shape the frontend posts as the intervened item; the outcome only reads its
# truthiness (an empty origin zeroes the economy) and stores it verbatim
ORIGIN = {
    "idDrug": DRUG,
    "name": "Medicamento de teste",
    "dose": "5.0",
    "frequencyDay": 2,
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


def _new_prescription(with_drug=True):
    """Create a prescription (optionally with one drug) on a fresh admission.

    Returns (admission, id_prescription, id_prescription_drug | None).
    """
    id_prescription = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1
    admission = test_counters["admission_number"]
    test_counters["admission_number"] += 1

    create_prescription(
        id=id_prescription,
        admissionNumber=admission,
        idPatient=1,
        date=datetime.now(),
        idDepartment=DEPARTMENT,
        idSegment=SEGMENT,
    )

    id_prescription_drug = None
    if with_drug:
        id_prescription_drug = int(f"{id_prescription}001")
        create_prescription_drug(
            id=id_prescription_drug,
            idPrescription=id_prescription,
            idDrug=DRUG,
            idSegment=SEGMENT,
        )

    return admission, id_prescription, id_prescription_drug


def _open_drug_intervention(client, headers, reason=REASON_CUSTOM_ECONOMY):
    """Open a pending intervention on a prescription drug.

    Returns (id_intervention, id_prescription, admission).
    """
    admission, id_prescription, id_prescription_drug = _new_prescription()

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

    return response.get_json()["data"][0]["idIntervention"], id_prescription, admission


def _open_prescription_intervention(client, headers, reason=REASON_CUSTOM_ECONOMY):
    """Open a pending intervention on the prescription itself (no item).

    Returns (id_intervention, id_prescription, admission).
    """
    admission, id_prescription, _ = _new_prescription(with_drug=False)

    response = client.put(
        INTERVENTION_URL,
        json={
            "status": "s",
            "admissionNumber": admission,
            "idInterventionReason": [reason],
            "idPrescription": str(id_prescription),
            "aggIdPrescription": str(id_prescription),
        },
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK

    return response.get_json()["data"][0]["idIntervention"], id_prescription, admission


def _outcome_data(client, headers, id_intervention, edit=None):
    """Read the outcome screen of an intervention."""
    query = {"idIntervention": id_intervention}
    if edit is not None:
        query["edit"] = edit

    response = client.get(OUTCOME_DATA_URL, query_string=query, headers=headers)

    assert response.status_code == status.HTTP_200_OK

    return response.get_json()["data"]


def _prescription_date(id_prescription: int) -> str:
    """The stored date of a prescription, as the payload renders it."""
    row = session.execute(
        text("SELECT dtprescricao FROM demo.prescricao WHERE fkprescricao = :id"),
        {"id": id_prescription},
    ).first()

    return row[0].isoformat()


def _stored(id_intervention) -> Intervention:
    """Re-read the intervention the endpoint wrote."""
    session.expire_all()

    return (
        session.query(Intervention)
        .filter(Intervention.idIntervention == id_intervention)
        .one()
    )


# --- intervention on a prescription drug --------------------------------------


def test_custom_economy_marks_both_figures_as_manual(client, analyst_headers):
    """A custom economy has no price to read, so the screen asks for both figures."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)

    header = _outcome_data(client, analyst_headers, id_intervention)["header"]

    assert header["economyType"] == InterventionEconomyTypeEnum.CUSTOM.value
    assert header["economyDayValueManual"] is True
    assert header["economyDayAmountManual"] is True
    # nothing was typed in yet: the screen opens empty
    assert header["economyDayValue"] is None
    assert header["economyDayAmount"] is None


def test_custom_economy_points_at_the_prescription_of_the_intervened_item(
    client, analyst_headers
):
    """idPrescription is 0 on an item intervention: the item supplies the prescription."""
    id_intervention, id_prescription, admission = _open_drug_intervention(
        client, analyst_headers
    )

    data = _outcome_data(client, analyst_headers, id_intervention)
    intervention = _stored(id_intervention)

    assert intervention.idPrescription == 0
    assert data["origin"] == {
        "item": {
            "idPrescription": str(id_prescription),
            "idPrescriptionAgg": prescriptionutils.gen_agg_id(
                admission_number=admission,
                id_segment=SEGMENT,
                pdate=intervention.date_base_economy,
            ),
            "prescriptionDate": _prescription_date(id_prescription),
        }
    }
    assert data["header"]["idSegment"] == SEGMENT


def test_custom_economy_carries_no_drug_comparison(client, analyst_headers):
    """The branch skips the price query, so nothing to substitute is offered."""
    data = _outcome_data(
        client, analyst_headers, _open_drug_intervention(client, analyst_headers)[0]
    )

    assert data.get("destiny") is None
    assert data.get("original") is None
    assert data["header"]["destinyDrug"] is None
    assert data["header"]["destinyDrugId"] is None
    assert data["header"]["destinyDrugSubstance"] is None
    # the intervened drug is still named, it is just not priced
    assert data["header"]["originDrug"] is not None


def test_custom_economy_reports_the_reason_and_the_base_date(client, analyst_headers):
    """The screen repeats the reason that granted the economy and where it starts."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)

    header = _outcome_data(client, analyst_headers, id_intervention)["header"]
    intervention = _stored(id_intervention)

    assert REASON_CUSTOM_LABEL in header["interventionReason"]
    assert intervention.date_base_economy is not None
    assert header["economyIniDate"] == intervention.date_base_economy.isoformat()
    assert header["economyEndDate"] is None


def test_custom_economy_shows_the_value_that_was_typed_in(client, analyst_headers):
    """Once closed, the screen reads the figures back from the record [readonly]."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)

    response = client.post(
        SET_OUTCOME_URL,
        json={
            "idIntervention": id_intervention,
            "outcome": "a",
            "origin": ORIGIN,
            "destiny": None,
            "idPrescriptionDrugDestiny": None,
            "economyDayValue": 12.75,
            "economyDayValueManual": True,
            "economyDayAmount": 4,
            "economyDayAmountManual": True,
        },
        headers=analyst_headers,
    )
    assert response.status_code == status.HTTP_200_OK

    header = _outcome_data(client, analyst_headers, id_intervention)["header"]

    assert header["readonly"] is True
    assert header["status"] == "a"
    assert float(header["economyDayValue"]) == 12.75
    assert header["economyDayAmount"] == 4
    assert header["outcomeUser"] is not None


def test_custom_economy_closed_without_an_origin_is_worth_nothing(
    client, analyst_headers
):
    """An empty origin voids the figure that was typed in: the economy becomes 0."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)

    response = client.post(
        SET_OUTCOME_URL,
        json={
            "idIntervention": id_intervention,
            "outcome": "a",
            "origin": None,
            "destiny": None,
            "idPrescriptionDrugDestiny": None,
            "economyDayValue": 99.9,
            "economyDayValueManual": True,
            "economyDayAmount": 2,
            "economyDayAmountManual": True,
        },
        headers=analyst_headers,
    )
    assert response.status_code == status.HTTP_200_OK

    header = _outcome_data(client, analyst_headers, id_intervention)["header"]

    assert float(header["economyDayValue"]) == 0
    assert header["economyDayValueManual"] is True


def test_custom_economy_reopens_for_editing(client, analyst_headers):
    """edit=True lifts the readonly flag a closed intervention otherwise carries."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)

    client.post(
        SET_OUTCOME_URL,
        json={
            "idIntervention": id_intervention,
            "outcome": "a",
            "origin": ORIGIN,
            "destiny": None,
            "idPrescriptionDrugDestiny": None,
            "economyDayValue": 1,
            "economyDayValueManual": True,
            "economyDayAmount": 1,
            "economyDayAmountManual": True,
        },
        headers=analyst_headers,
    )

    assert (
        _outcome_data(client, analyst_headers, id_intervention, edit="True")["header"][
            "readonly"
        ]
        is False
    )


# --- intervention on the prescription -----------------------------------------


def test_prescription_intervention_keeps_its_custom_economy(client, analyst_headers):
    """A prescription-level intervention is the one kind that may carry an economy."""
    id_intervention, id_prescription, admission = _open_prescription_intervention(
        client, analyst_headers
    )

    data = _outcome_data(client, analyst_headers, id_intervention)
    intervention = _stored(id_intervention)

    assert intervention.idPrescription == id_prescription
    assert data["header"]["economyType"] == InterventionEconomyTypeEnum.CUSTOM.value
    assert data["header"]["idSegment"] == SEGMENT
    assert data["origin"]["item"]["idPrescription"] == str(id_prescription)
    assert data["origin"]["item"]["idPrescriptionAgg"] == prescriptionutils.gen_agg_id(
        admission_number=admission,
        id_segment=SEGMENT,
        pdate=intervention.date_base_economy,
    )
    # no intervened item: the drug columns stay empty
    assert data["header"]["originDrug"] is None


def test_prescription_intervention_without_custom_economy_has_none(
    client, analyst_headers
):
    """A suspension reason on a prescription is dropped: only custom survives there."""
    id_intervention, _, _ = _open_prescription_intervention(
        client, analyst_headers, reason=REASON_SUSPENSION
    )

    data = _outcome_data(client, analyst_headers, id_intervention)

    assert _stored(id_intervention).economy_type is None
    # no economy, no origin block -- the short header is returned instead
    assert "origin" not in data
    assert data["header"]["status"] == "s"


# --- guards -------------------------------------------------------------------


def test_outcome_data_rejects_an_unknown_intervention(client, analyst_headers):
    """An id no intervention carries is refused [400 BAD REQUEST]."""
    response = client.get(
        OUTCOME_DATA_URL,
        query_string={"idIntervention": MISSING_ID},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"


def test_outcome_data_requires_read_prescription(client):
    """SUPPORT_REQUESTER cannot read a prescription, so the screen is closed [401]."""
    headers = make_headers(get_access(client, roles=[Role.SUPPORT_REQUESTER.value]))

    response = client.get(
        OUTCOME_DATA_URL,
        query_string={"idIntervention": MISSING_ID},
        headers=headers,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_outcome_data_requires_authentication(client):
    """No token, no screen [401]."""
    response = client.get(
        OUTCOME_DATA_URL, query_string={"idIntervention": MISSING_ID}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
