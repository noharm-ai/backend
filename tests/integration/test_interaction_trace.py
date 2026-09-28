"""Integration tests for the drug interaction trace
(``GET /prescriptions/interaction-trace``, interaction_trace_service).

The trace replays ``alert_interaction_service`` for a pair of items of a real
prescription and explains, step by step, why an interaction alert was or was
not raised: whether each item takes part in the analysis, whether the pair is
compared at all, which relations are registered between the substances and
which kind-specific rule stopped an alert. It is a support tool, so only
maintainers can reach it.

Substances, drugs and relations come from the fixtures of
``test_prescription_interactions.py`` and are removed by them.
"""

from datetime import datetime

import pytest

from security.role import Role
from tests.conftest import get_access, make_headers
from tests.integration.test_prescription_interactions import (  # noqa: F401
    _DRUG_A,
    _DRUG_ALLERGEN,
    _DRUG_B,
    _DRUG_NO_SUBSTANCE,
    _SEED_PATIENT,
    _SUBSTANCE_A,
    _SUBSTANCE_ALLERGEN,
    _SUBSTANCE_B,
    _add_relation,
    _register_allergy,
    seed_substances_and_drugs,
)
from tests.utils import utils_test_prescription

_URL = "/prescriptions/interaction-trace"

pytestmark = pytest.mark.usefixtures("seed_substances_and_drugs")


@pytest.fixture
def maintainer_headers(client):
    """Headers with CURATOR role, which holds the MAINTAINER permission"""
    return make_headers(get_access(client, roles=[Role.CURATOR.value]))


def _prescription(drugs: list[dict]) -> tuple[int, list[int]]:
    """Creates a prescription with the given drugs, returning its id and the
    prescription drug ids in the same order"""
    prescription = utils_test_prescription.create_basic_prescription()

    base_id = int(f"{prescription.id}010")
    for offset, drug in enumerate(drugs):
        utils_test_prescription.create_prescription_drug(
            id=base_id + offset, idPrescription=prescription.id, **drug
        )

    return prescription.id, [base_id + offset for offset in range(len(drugs))]


def _trace(client, headers, **params) -> dict:
    response = client.get(_URL, query_string=params, headers=headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def _kind(trace: dict, kind: str) -> dict:
    return next(k for k in trace["kinds"] if k["kind"] == kind)


def test_only_maintainers_can_trace(client, analyst_headers):
    """A pharmacist reads the alerts but cannot open the support trace."""
    id_prescription, _ = _prescription([{"idDrug": _DRUG_A[0]}])

    response = client.get(
        _URL, query_string={"idPrescription": id_prescription}, headers=analyst_headers
    )

    assert response.status_code == 401


def test_without_a_pair_it_lists_the_selectable_items(client, maintainer_headers):
    """The first call feeds the item pickers, flagging what is left out."""
    _register_allergy(_SEED_PATIENT, _DRUG_ALLERGEN[0])
    id_prescription, (id_a, id_none) = _prescription(
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_NO_SUBSTANCE[0]}]
    )

    data = _trace(client, maintainer_headers, idPrescription=id_prescription)

    assert data["trace"] is None
    items = {i["idPrescriptionDrug"]: i for i in data["items"]}
    assert items[str(id_a)]["eligible"] is True
    assert items[str(id_none)]["eligible"] is False
    assert "substância" in items[str(id_none)]["ineligibilityReason"]
    assert {"sctid": str(_SUBSTANCE_ALLERGEN[0]), "name": _SUBSTANCE_ALLERGEN[1]} in (
        data["allergies"]
    )


def test_an_alerted_pair_explains_the_alert(client, maintainer_headers):
    """An active relation that passes its rules is reported as the alert."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")
    id_prescription, (id_a, id_b) = _prescription(
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}]
    )

    trace = _trace(
        client,
        maintainer_headers,
        idPrescription=id_prescription,
        idPrescriptionDrugFrom=id_a,
        idPrescriptionDrugTo=id_b,
    )["trace"]

    assert trace["compared"] is True
    assert trace["alerted"] is True
    assert "Interação Medicamentosa" in trace["summary"]

    direction = _kind(trace, "it")["directions"][0]
    assert direction["alerted"] is True
    assert direction["alert"]["level"] == "high"
    assert direction["alert"]["shownOn"] == [_DRUG_A[1], _DRUG_B[1]]

    # the relation is registered A -> B only, so B -> A finds nothing
    assert _kind(trace, "it")["directions"][1]["relation"] is None


def test_no_registered_relation_is_the_reason(client, maintainer_headers):
    """With nothing in relacao, the trace says so instead of guessing."""
    id_prescription, (id_a, id_b) = _prescription(
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}]
    )

    trace = _trace(
        client,
        maintainer_headers,
        idPrescription=id_prescription,
        idPrescriptionDrugFrom=id_a,
        idPrescriptionDrugTo=id_b,
    )["trace"]

    assert trace["alerted"] is False
    assert trace["relations"] == []
    assert "não há relação cadastrada" in trace["summary"]


def test_an_inactive_relation_is_shown_as_inactive(client, maintainer_headers):
    """A retired relation is still listed, so support sees why it is silent."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high", active=False)
    id_prescription, (id_a, id_b) = _prescription(
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}]
    )

    trace = _trace(
        client,
        maintainer_headers,
        idPrescription=id_prescription,
        idPrescriptionDrugFrom=id_a,
        idPrescriptionDrugTo=id_b,
    )["trace"]

    assert trace["alerted"] is False
    assert trace["relations"][0]["active"] is False
    assert "inativa" in _kind(trace, "it")["directions"][0]["message"]


def test_a_suspended_item_is_not_compared(client, maintainer_headers):
    """An ineligible item stops the analysis before any relation is read."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")
    id_prescription, (id_a, id_b) = _prescription(
        [
            {"idDrug": _DRUG_A[0]},
            {"idDrug": _DRUG_B[0], "suspendedDate": datetime.now()},
        ]
    )

    trace = _trace(
        client,
        maintainer_headers,
        idPrescription=id_prescription,
        idPrescriptionDrugFrom=id_a,
        idPrescriptionDrugTo=id_b,
    )["trace"]

    assert trace["compared"] is False
    assert trace["alerted"] is False
    assert trace["kinds"] == []
    assert "suspenso" in trace["summary"]
    # the relation that would have alerted is still shown
    assert trace["relations"][0]["kind"] == "it"


def test_the_failing_kind_rule_is_reported(client, maintainer_headers):
    """``iy`` needs two intravenous drugs: the trace names the failing rule."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "iy", "high")
    id_prescription, (id_a, id_b) = _prescription(
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}]
    )

    trace = _trace(
        client,
        maintainer_headers,
        idPrescription=id_prescription,
        idPrescriptionDrugFrom=id_a,
        idPrescriptionDrugTo=id_b,
    )["trace"]

    assert trace["alerted"] is False
    rules = _kind(trace, "iy")["directions"][0]["rules"]
    failed = [r["rule"] for r in rules if not r["passed"]]
    assert failed == ["intravenous"]
    assert "regras" in trace["summary"]


def test_a_cross_reactivity_pair_with_an_allergy(client, maintainer_headers):
    """The second item can be one of the patient's allergies."""
    _register_allergy(_SEED_PATIENT, _DRUG_ALLERGEN[0])
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_ALLERGEN[0], "rx", "high")
    id_prescription, (id_a,) = _prescription([{"idDrug": _DRUG_A[0]}])

    trace = _trace(
        client,
        maintainer_headers,
        idPrescription=id_prescription,
        idPrescriptionDrugFrom=id_a,
        sctidAllergy=_SUBSTANCE_ALLERGEN[0],
    )["trace"]

    assert trace["isAllergy"] is True
    assert trace["alerted"] is True
    assert [k["kind"] for k in trace["kinds"]] == ["rx"]
    assert trace["kinds"][0]["directions"][0]["alert"]["shownOn"] == [_DRUG_A[1]]


def test_a_cross_reactivity_registered_the_other_way_is_flagged(
    client, maintainer_headers
):
    """Only drug -> allergy is evaluated; the reverse row is explained."""
    _register_allergy(_SEED_PATIENT, _DRUG_ALLERGEN[0])
    _add_relation(_SUBSTANCE_ALLERGEN[0], _SUBSTANCE_A[0], "rx", "high")
    id_prescription, (id_a,) = _prescription([{"idDrug": _DRUG_A[0]}])

    trace = _trace(
        client,
        maintainer_headers,
        idPrescription=id_prescription,
        idPrescriptionDrugFrom=id_a,
        sctidAllergy=_SUBSTANCE_ALLERGEN[0],
    )["trace"]

    assert trace["alerted"] is False
    assert len(trace["notes"]) == 1


def test_the_trace_agrees_with_the_prescription_alerts(
    client, analyst_headers, maintainer_headers
):
    """The trace and the prescription view share the same rules."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "dm", "high")
    id_prescription, (id_a, id_b) = _prescription(
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0], "frequency": 66.0}]
    )

    payload = client.get(
        f"/prescriptions/{id_prescription}", headers=analyst_headers
    ).get_json()["data"]
    assert payload["alertStats"]["interactions"].get("dm", 0) == 0

    trace = _trace(
        client,
        maintainer_headers,
        idPrescription=id_prescription,
        idPrescriptionDrugFrom=id_a,
        idPrescriptionDrugTo=id_b,
    )["trace"]

    assert trace["alerted"] is False
    rules = _kind(trace, "dm")["directions"][0]["rules"]
    assert [r["rule"] for r in rules if not r["passed"]] == ["not_now_frequency"]


def test_the_same_item_twice_is_rejected(client, maintainer_headers):
    """An item is never compared with itself."""
    id_prescription, (id_a,) = _prescription([{"idDrug": _DRUG_A[0]}])

    response = client.get(
        _URL,
        query_string={
            "idPrescription": id_prescription,
            "idPrescriptionDrugFrom": id_a,
            "idPrescriptionDrugTo": id_a,
        },
        headers=maintainer_headers,
    )

    assert response.status_code == 400
