"""Tests: intervention search filters (POST /intervention/search).

The search endpoint feeds the "Intervenções" screen and every report built on
top of it. It is a single query with a dozen optional filters (period, segment,
drug, prescription, reason, economy, status, responsible, prescriber) plus the
fallbacks used to name the drug of an intervention whose prescription is no
longer available.

Each test builds its own interventions and always scopes the search to the test
admission, so seed interventions never interfere with the assertions.
"""

from datetime import datetime, timedelta

import pytest

from models.prescription import Intervention
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)

# ids reserved for this module, well above the sequence used in production data
FIRST_INTERVENTION_ID = 990000

TODAY = datetime.today()
OLD_DATE = TODAY - timedelta(days=5)

# user 1 ("Demonstração") is the logged-in analyst; user 2 is "User Admin"
RESPONSIBLE = 1
OTHER_RESPONSIBLE = 2

# seeded drugs
ANLODIPINO = 3
BISACODIL = 4
# no drug carries this id, so the search has to fall back to a generic name
UNKNOWN_DRUG = 777777
# no prescribed item carries this id, so the intervention reads as archived
ARCHIVED_PRESCRIPTION_DRUG = 888888

PRESCRIBER = "Dr. Fulano Beltrano"
OTHER_PRESCRIBER = "Dra. Ciclana de Tal"

# department 1 belongs to segment 1 and department 3 to segment 2
OTHER_DEPARTMENT = 3
SEGMENT = 1
OTHER_SEGMENT = 2

# intervention reasons present in the seed data
REASON_APRAZAMENTO = 2
REASON_APRESENTACAO = 3
REASON_DOSE = 12

ECONOMY_TYPE_SUBSTITUTION = 2


class _Dataset:
    """Ids of the records created by the ``dataset`` fixture."""

    def __init__(self, admission, prescriptions, drugs, interventions):
        self.admission = admission
        self.prescriptions = prescriptions
        self.drugs = drugs
        self.interventions = interventions


def _add_intervention(
    id_intervention: int,
    id_prescription_drug: int,
    admission_number: int,
    reasons: list,
    status="s",
    date=None,
    user=RESPONSIBLE,
    economy_type=None,
    id_prescription=0,
):
    """Persist one intervention for the search tests."""
    intervention = Intervention()
    intervention.idIntervention = id_intervention
    intervention.id = id_prescription_drug
    intervention.idPrescription = id_prescription
    intervention.admissionNumber = admission_number
    intervention.idInterventionReason = reasons
    intervention.idDepartment = 1
    intervention.status = status
    intervention.date = date or TODAY
    intervention.update = date or TODAY
    intervention.user = user
    intervention.economy_type = economy_type
    intervention.economy_day_value_manual = False

    session.add(intervention)

    return id_intervention


@pytest.fixture(scope="module")
def dataset():
    """Five interventions on one admission, each differing on a single filter.

    * ``current`` — segment 1, anlodipino, today, no economy, status "s"
    * ``old`` — segment 2, bisacodil, five days ago, economy, status "a",
      another responsible and another prescriber
    * ``unknown_drug`` — prescribed item whose drug is not in the catalogue
    * ``archived`` — intervention whose prescribed item no longer exists
    * ``patient`` — intervention on the patient instead of on a drug
    """
    admission = test_counters["admission_number"]
    id_prescription = test_counters["id_prescription"]
    other_id_prescription = id_prescription + 1
    test_counters["admission_number"] += 1
    test_counters["id_prescription"] += 2

    create_prescription(
        id=id_prescription,
        admissionNumber=admission,
        idPatient=1,
        idSegment=SEGMENT,
        prescriber=PRESCRIBER,
    )
    create_prescription(
        id=other_id_prescription,
        admissionNumber=admission,
        idPatient=1,
        # a prescription takes its segment from the department (see segmentosetor);
        # department 3 is the one mapped to segment 2
        idDepartment=OTHER_DEPARTMENT,
        prescriber=OTHER_PRESCRIBER,
    )

    current_drug = int(f"{id_prescription}001")
    old_drug = int(f"{other_id_prescription}001")
    unknown_drug = int(f"{id_prescription}002")

    create_prescription_drug(
        id=current_drug, idPrescription=id_prescription, idDrug=ANLODIPINO
    )
    create_prescription_drug(
        id=old_drug,
        idPrescription=other_id_prescription,
        idDrug=BISACODIL,
        idSegment=OTHER_SEGMENT,
    )
    create_prescription_drug(
        id=unknown_drug, idPrescription=id_prescription, idDrug=UNKNOWN_DRUG
    )

    interventions = {
        "current": _add_intervention(
            id_intervention=FIRST_INTERVENTION_ID,
            id_prescription_drug=current_drug,
            admission_number=admission,
            reasons=[REASON_APRAZAMENTO],
        ),
        "old": _add_intervention(
            id_intervention=FIRST_INTERVENTION_ID + 1,
            id_prescription_drug=old_drug,
            admission_number=admission,
            reasons=[REASON_APRESENTACAO],
            status="a",
            date=OLD_DATE,
            user=OTHER_RESPONSIBLE,
            economy_type=ECONOMY_TYPE_SUBSTITUTION,
        ),
        "unknown_drug": _add_intervention(
            id_intervention=FIRST_INTERVENTION_ID + 2,
            id_prescription_drug=unknown_drug,
            admission_number=admission,
            reasons=[REASON_APRAZAMENTO, REASON_DOSE],
        ),
        "archived": _add_intervention(
            id_intervention=FIRST_INTERVENTION_ID + 3,
            id_prescription_drug=ARCHIVED_PRESCRIPTION_DRUG,
            admission_number=admission,
            reasons=[REASON_APRAZAMENTO],
        ),
        "patient": _add_intervention(
            id_intervention=FIRST_INTERVENTION_ID + 4,
            id_prescription_drug=0,
            admission_number=admission,
            reasons=[REASON_APRAZAMENTO],
            id_prescription=id_prescription,
        ),
    }
    session_commit()

    yield _Dataset(
        admission=admission,
        prescriptions={"current": id_prescription, "old": other_id_prescription},
        drugs={
            "current": current_drug,
            "old": old_drug,
            "unknown_drug": unknown_drug,
        },
        interventions=interventions,
    )

    session.query(Intervention).filter(
        Intervention.idIntervention >= FIRST_INTERVENTION_ID
    ).delete(synchronize_session=False)
    session_commit()


def _search(client, headers, dataset: _Dataset, **filters):
    """Search the test admission with the given extra filters."""
    payload = {"admissionNumber": dataset.admission}
    payload.update(filters)

    response = client.post("/intervention/search", json=payload, headers=headers)

    assert response.status_code == 200

    return response.get_json()["data"]


def _found_ids(result):
    """Intervention ids of a search result, as integers."""
    return {int(i["idIntervention"]) for i in result}


def _by_id(result, id_intervention: int):
    """Single entry of a search result."""
    found = [i for i in result if int(i["idIntervention"]) == id_intervention]

    assert len(found) == 1

    return found[0]


def test_search_requires_a_period_or_an_admission(client, analyst_headers):
    """An unbounded search is rejected: it would scan every intervention ever made"""
    response = client.post("/intervention/search", json={}, headers=analyst_headers)

    assert response.status_code == 400
    assert response.get_json()["message"] == "Data inicial inválida"


def test_search_by_admission_returns_every_intervention(
    client, analyst_headers, dataset
):
    """An admission alone is enough: no start date is required"""
    result = _search(client, analyst_headers, dataset)

    assert _found_ids(result) == set(dataset.interventions.values())


def test_search_end_date_excludes_later_interventions(client, analyst_headers, dataset):
    """endDate keeps only what was registered up to the end of that day"""
    result = _search(
        client,
        analyst_headers,
        dataset,
        endDate=(TODAY - timedelta(days=3)).isoformat(),
    )

    assert _found_ids(result) == {dataset.interventions["old"]}


def test_search_start_date_excludes_earlier_interventions(
    client, analyst_headers, dataset
):
    """startDate drops what was registered before it"""
    result = _search(
        client,
        analyst_headers,
        dataset,
        startDate=(TODAY - timedelta(days=1)).isoformat(),
    )

    assert dataset.interventions["old"] not in _found_ids(result)
    assert dataset.interventions["current"] in _found_ids(result)


@pytest.mark.parametrize(
    "id_segment, expected",
    [
        (SEGMENT, ["current", "unknown_drug", "patient"]),
        (OTHER_SEGMENT, ["old"]),
    ],
)
def test_search_by_segment(client, analyst_headers, dataset, id_segment, expected):
    """The segment comes from the prescription of the drug, or of the intervention"""
    result = _search(client, analyst_headers, dataset, idSegment=id_segment)

    assert _found_ids(result) == {dataset.interventions[k] for k in expected}


def test_search_by_drug(client, analyst_headers, dataset):
    """idDrug keeps only the interventions made on those drugs"""
    result = _search(client, analyst_headers, dataset, idDrug=[BISACODIL])

    assert _found_ids(result) == {dataset.interventions["old"]}


def test_search_by_prescription(client, analyst_headers, dataset):
    """idPrescription matches the prescription the intervention itself points to"""
    result = _search(
        client,
        analyst_headers,
        dataset,
        idPrescription=dataset.prescriptions["current"],
    )

    # only the patient intervention is tied to a prescription instead of a drug
    assert _found_ids(result) == {dataset.interventions["patient"]}


def test_search_by_prescription_drug(client, analyst_headers, dataset):
    """idPrescriptionDrug matches the prescribed item the intervention was made on"""
    result = _search(
        client,
        analyst_headers,
        dataset,
        idPrescriptionDrug=dataset.drugs["old"],
    )

    assert _found_ids(result) == {dataset.interventions["old"]}


def test_search_by_reason_matches_any_of_the_selected_reasons(
    client, analyst_headers, dataset
):
    """An intervention is kept when it carries at least one of the selected reasons"""
    result = _search(
        client,
        analyst_headers,
        dataset,
        idInterventionReasonList=[REASON_DOSE, REASON_APRESENTACAO],
    )

    assert _found_ids(result) == {
        dataset.interventions["unknown_drug"],
        dataset.interventions["old"],
    }


@pytest.mark.parametrize(
    "has_economy, expected",
    [
        (True, ["old"]),
        (False, ["current", "unknown_drug", "archived", "patient"]),
    ],
)
def test_search_by_economy(client, analyst_headers, dataset, has_economy, expected):
    """hasEconomy splits the interventions that carry an economy type from the rest"""
    result = _search(client, analyst_headers, dataset, hasEconomy=has_economy)

    assert _found_ids(result) == {dataset.interventions[k] for k in expected}


def test_search_ignores_an_empty_economy_filter(client, analyst_headers, dataset):
    """An empty hasEconomy is the "both" option of the screen, not a false"""
    result = _search(client, analyst_headers, dataset, hasEconomy="")

    assert _found_ids(result) == set(dataset.interventions.values())


def test_search_by_status(client, analyst_headers, dataset):
    """statusList keeps only the interventions in one of the selected statuses"""
    result = _search(client, analyst_headers, dataset, statusList=["a"])

    assert _found_ids(result) == {dataset.interventions["old"]}


def test_search_by_responsible_name(client, analyst_headers, dataset):
    """responsibleName matches part of the name of who registered the intervention"""
    result = _search(client, analyst_headers, dataset, responsibleName="User Admin")

    assert _found_ids(result) == {dataset.interventions["old"]}
    assert _by_id(result, dataset.interventions["old"])["user"] == "User Admin"


def test_search_by_prescriber_name(client, analyst_headers, dataset):
    """prescriberName matches part of the prescriber of the drug's prescription"""
    result = _search(client, analyst_headers, dataset, prescriberName="Ciclana")

    assert _found_ids(result) == {dataset.interventions["old"]}
    assert _by_id(result, dataset.interventions["old"])["prescriber"] == (
        OTHER_PRESCRIBER
    )


def test_search_names_a_drug_that_is_not_in_the_catalogue(
    client, analyst_headers, dataset
):
    """A prescribed item pointing to an unknown drug is reported by its id"""
    result = _search(client, analyst_headers, dataset)

    entry = _by_id(result, dataset.interventions["unknown_drug"])

    assert entry["drugName"] == f"Medicamento {UNKNOWN_DRUG}"


def test_search_names_an_archived_intervention(client, analyst_headers, dataset):
    """An intervention whose prescribed item is gone is reported as archived"""
    result = _search(client, analyst_headers, dataset)

    entry = _by_id(result, dataset.interventions["archived"])

    assert entry["drugName"] == "Intervenção arquivada"
    assert entry["idSegment"] is None


def test_search_names_an_intervention_made_on_the_patient(
    client, analyst_headers, dataset
):
    """An intervention registered on the patient has no drug to name"""
    result = _search(client, analyst_headers, dataset)

    entry = _by_id(result, dataset.interventions["patient"])

    assert entry["drugName"] == "Intervenção no Paciente"


def test_search_requires_read_prescription(client, user_manager_headers, dataset):
    """A user without READ_PRESCRIPTION cannot list interventions"""
    response = client.post(
        "/intervention/search",
        json={"admissionNumber": dataset.admission},
        headers=user_manager_headers,
    )

    assert response.status_code == 401
