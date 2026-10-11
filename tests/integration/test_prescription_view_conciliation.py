"""Tests: the conciliation list of GET /prescriptions/<idPrescription>

A conciliation prescription (``concilia = 's'``) holds the drugs the patient
used at home. To reconcile them, the screen puts them side by side with what
the patient is getting in the hospital: the ``conciliaList`` of the view, plus
the links the pharmacist drew between the two lists (``conciliaRelations``).
``prescription_view_service._get_drug_data`` builds that pair in two ways:

* once the conciliation is checked, the pair is read back from the CHECK audit
  that POST /prescriptions/status wrote, so the pharmacist sees exactly what
  they reconciled, even if the hospital prescription changed afterwards;
* before that (or when the check carried no list), the list is built from the
  patient's current aggregated prescription: active drugs, solutions and
  procedures, without suspended items or diets, and without repeating an item
  prescribed twice in the same way.

A regular prescription never gets a conciliation list.
"""

from datetime import datetime

import pytest
from sqlalchemy import text

from models.enums import DrugTypeEnum
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from tests.conftest import session, session_commit

STATUS_URL = "/prescriptions/status"

# seed drugs (demo.medicamento)
HOME_DRUG = 7  # DIAZEPAM 10 mg CP: what the patient took at home
DRUG_A = 2  # ALOPURINOL 100 mg CP
DRUG_B = 3  # ANLODIPINO 10 mg CP
DRUG_C = 10  # ENALAPRIL 20 mg CP
DRUG_D = 15  # PARACETAMOL 500 mg CP

# what the pharmacist sends when checking the conciliation
SENT_LIST = [
    {
        "idPrescriptionDrug": "900001",
        "idDrug": str(DRUG_A),
        "drug": "ALOPURINOL 100 mg CP",
    }
]
SENT_RELATIONS = [{"idPrescriptionDrug": "900002", "relation": "900001"}]


def _reserve() -> tuple[int, int]:
    """Reserve a prescription id block and an admission for one patient."""
    id_prescription = test_counters["id_prescription"]
    admission = test_counters["admission_number"]

    test_counters["id_prescription"] += 10
    test_counters["admission_number"] += 1

    return id_prescription, admission


def _item_id(id_prescription: int, n: int) -> int:
    """A presmed id derived from its prescription, above the cleanup threshold."""
    return int(f"{id_prescription}{n:03d}")


def _create_conciliation(id_prescription: int, admission: int) -> int:
    """A conciliation prescription with one home drug."""
    create_prescription(
        id=id_prescription,
        admissionNumber=admission,
        idPatient=1,
        concilia="s",
        date=datetime.now(),
    )
    create_prescription_drug(
        id=_item_id(id_prescription, 1),
        idPrescription=id_prescription,
        idDrug=HOME_DRUG,
    )

    return id_prescription


def _create_hospital_prescription(
    id_agg: int, admission: int, items: list[dict]
) -> list[int]:
    """The current aggregated prescription of the admission.

    The aggregation reads its items from the individual prescription
    underneath it, which is written with ``items`` (``create_prescription_drug``
    keyword arguments). Returns the presmed ids, in order.
    """
    date = datetime.now()
    id_internal = id_agg + 1

    create_prescription(
        id=id_agg, admissionNumber=admission, idPatient=1, agg=True, date=date
    )
    create_prescription(
        id=id_internal, admissionNumber=admission, idPatient=1, date=date
    )

    ids = []
    for n, item in enumerate(items, start=1):
        id_item = _item_id(id_internal, n)
        create_prescription_drug(id=id_item, idPrescription=id_internal, **item)
        ids.append(id_item)

    return ids


def _view(client, headers, id_prescription: int) -> dict:
    """GET the prescription view and return its ``data`` payload."""
    response = client.get(f"/prescriptions/{id_prescription}", headers=headers)
    assert response.status_code == 200

    return response.get_json()["data"]


def _check(client, headers, id_prescription: int, **extra) -> None:
    """Check a prescription through the API."""
    response = client.post(
        STATUS_URL,
        json={"idPrescription": str(id_prescription), "status": "s", **extra},
        headers=headers,
    )
    assert response.status_code == 200


def _set_checked(id_prescription: int) -> None:
    """Flag a prescription as checked, leaving no CHECK audit behind."""
    session.execute(
        text("UPDATE demo.prescricao SET status = 's' WHERE fkprescricao = :id"),
        {"id": id_prescription},
    )
    session_commit()


@pytest.fixture
def admission() -> tuple[int, int, list[int]]:
    """A conciliation for a fresh admission whose hospital prescription has
    two drugs. Returns ``(id_conciliation, id_agg, hospital_item_ids)``."""
    id_block, adm = _reserve()
    id_conciliation = _create_conciliation(id_block, adm)
    id_agg = id_block + 2
    item_ids = _create_hospital_prescription(
        id_agg,
        adm,
        [{"idDrug": DRUG_A}, {"idDrug": DRUG_B, "dose": 5.0}],
    )

    return id_conciliation, id_agg, item_ids


def test_checked_conciliation_shows_what_was_reconciled(
    client, analyst_headers, admission
):
    """After the check, the list and the links come back as they were sent."""
    id_conciliation, _, _ = admission

    _check(
        client,
        analyst_headers,
        id_conciliation,
        conciliaList=SENT_LIST,
        conciliaRelations=SENT_RELATIONS,
    )

    data = _view(client, analyst_headers, id_conciliation)

    assert data["status"] == "s"
    assert data["conciliaList"] == SENT_LIST
    assert data["conciliaRelations"] == SENT_RELATIONS


def test_checked_conciliation_shows_the_latest_check(
    client, analyst_headers, admission
):
    """Checked, unchecked and checked again: the second check is what shows."""
    id_conciliation, _, _ = admission
    second_list = [dict(SENT_LIST[0], drug="ALOPURINOL REVISTO")]

    _check(
        client,
        analyst_headers,
        id_conciliation,
        conciliaList=SENT_LIST,
        conciliaRelations=SENT_RELATIONS,
    )
    response = client.post(
        STATUS_URL,
        json={"idPrescription": str(id_conciliation), "status": "0"},
        headers=analyst_headers,
    )
    assert response.status_code == 200
    _check(
        client,
        analyst_headers,
        id_conciliation,
        conciliaList=second_list,
        conciliaRelations=[],
    )

    data = _view(client, analyst_headers, id_conciliation)

    assert data["conciliaList"] == second_list
    assert data["conciliaRelations"] == []


def test_checked_conciliation_without_a_list_uses_the_hospital_prescription(
    client, analyst_headers, admission
):
    """A check that sent no list falls back to the current hospital drugs,
    and has no links to show."""
    id_conciliation, _, item_ids = admission

    _check(client, analyst_headers, id_conciliation)

    data = _view(client, analyst_headers, id_conciliation)

    assert [d["idPrescriptionDrug"] for d in data["conciliaList"]] == [
        str(i) for i in item_ids
    ]
    assert data["conciliaRelations"] == []


def test_checked_conciliation_without_an_audit_uses_the_hospital_prescription(
    client, analyst_headers, admission
):
    """Checked with no CHECK audit behind it: built from the hospital drugs."""
    id_conciliation, _, item_ids = admission

    _set_checked(id_conciliation)

    data = _view(client, analyst_headers, id_conciliation)

    assert data["status"] == "s"
    assert [d["idPrescriptionDrug"] for d in data["conciliaList"]] == [
        str(i) for i in item_ids
    ]
    assert data["conciliaRelations"] == []


def test_pending_conciliation_lists_the_hospital_drugs(
    client, analyst_headers, admission
):
    """Before the check, each hospital drug comes with its prescription data."""
    id_conciliation, _, item_ids = admission

    data = _view(client, analyst_headers, id_conciliation)
    items = {d["idPrescriptionDrug"]: d for d in data["conciliaList"]}

    assert set(items) == {str(i) for i in item_ids}

    first = items[str(item_ids[0])]
    assert first["idDrug"] == str(DRUG_A)
    assert first["drug"] == "ALOPURINOL 100 mg CP"
    assert first["dose"] == 100.0
    assert first["frequencyday"] == 1.0

    assert items[str(item_ids[1])]["dose"] == 5.0
    assert data["conciliaRelations"] == []


def test_pending_conciliation_skips_suspended_items_and_diets(client, analyst_headers):
    """Suspended items and diets are not offered for reconciliation, while
    solutions and procedures are."""
    id_block, adm = _reserve()
    id_conciliation = _create_conciliation(id_block, adm)
    active, suspended, diet, solution, procedure = _create_hospital_prescription(
        id_block + 2,
        adm,
        [
            {"idDrug": DRUG_A},
            {"idDrug": DRUG_B, "suspendedDate": datetime.now()},
            {"idDrug": DRUG_C, "source": DrugTypeEnum.DIET.value},
            {"idDrug": DRUG_D, "source": DrugTypeEnum.SOLUTION.value},
            {"idDrug": DRUG_C, "source": DrugTypeEnum.PROCEDURE.value},
        ],
    )

    data = _view(client, analyst_headers, id_conciliation)
    listed = {d["idPrescriptionDrug"] for d in data["conciliaList"]}

    assert listed == {str(active), str(solution), str(procedure)}
    assert str(suspended) not in listed
    assert str(diet) not in listed


def test_pending_conciliation_lists_a_repeated_item_once(client, analyst_headers):
    """The same drug prescribed twice the same way is listed once; prescribed
    with another dose, it is a different item."""
    id_block, adm = _reserve()
    id_conciliation = _create_conciliation(id_block, adm)
    first, repeated, other_dose = _create_hospital_prescription(
        id_block + 2,
        adm,
        [
            {"idDrug": DRUG_A},
            {"idDrug": DRUG_A},
            {"idDrug": DRUG_A, "dose": 300.0},
        ],
    )

    data = _view(client, analyst_headers, id_conciliation)
    listed = [d for d in data["conciliaList"] if d["idDrug"] == str(DRUG_A)]

    assert len(listed) == 2
    assert {d["dose"] for d in listed} == {100.0, 300.0}
    assert str(other_dose) in {d["idPrescriptionDrug"] for d in listed}
    # one of the two identical items stands for both
    assert (
        len({str(first), str(repeated)} & {d["idPrescriptionDrug"] for d in listed})
        == 1
    )


def test_pending_conciliation_without_a_hospital_prescription(client, analyst_headers):
    """With nothing prescribed in the hospital, there is nothing to reconcile."""
    id_block, adm = _reserve()
    id_conciliation = _create_conciliation(id_block, adm)

    data = _view(client, analyst_headers, id_conciliation)

    assert data["conciliaList"] == []
    assert data["conciliaRelations"] == []


def test_regular_prescription_has_no_conciliation_list(
    client, analyst_headers, admission
):
    """The aggregated hospital prescription itself is not a conciliation."""
    _, id_agg, _ = admission

    data = _view(client, analyst_headers, id_agg)

    assert data["concilia"] is None
    assert data["conciliaList"] == []
    assert data["conciliaRelations"] == []
