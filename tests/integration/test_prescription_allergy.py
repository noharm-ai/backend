"""Integration tests for the direct allergy alert of ``GET /prescriptions/<id>``.

The allergy flag of a prescribed item (presmed.alergia) is set by the
integration when the item arrives, so the prescription view confirms it with the
patient's allergy records (alergia): an allergy recorded after the item arrived
raises the alert, one inactivated afterwards drops it, and with no record of the
item the flag stands. The item's ``allergy`` flag in the payload follows the
same decision.

A record is of the item by its sctid when it has one (resolved by a separate
job, fkmedicamento does not always reference a medicamento record); otherwise
by fkmedicamento. The same sctid also reaches the cross reactivity check.

The allergies are recorded after the items arrive: the presmed insert
(complete_presmed_v2, noharm-ai/database) already flags an item whose allergy
was recorded before it.

Substances and drugs come from the fixtures of
``test_prescription_interactions.py``, which also remove the allergy records
(fkmedicamento >= 90000).
"""

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.utils import utils_test_prescription
from tests.integration.test_prescription_interactions import (  # noqa: F401
    _DRUG_A,
    _DRUG_B,
    _SEED_PATIENT,
    _SUBSTANCE_A,
    _SUBSTANCE_ALLERGEN,
    _SUBSTANCE_B,
    _add_relation,
    _alerts_of,
    _count,
    _register_allergy,
    seed_substances_and_drugs,
)

pytestmark = pytest.mark.usefixtures("seed_substances_and_drugs")

# allergy codes that reference no medicamento record (>= 90000: cleaned up)
_UNMAPPED_CODE = 99101
_OTHER_UNMAPPED_CODE = 99102


def _register_allergy_by_substance(
    id_patient: int, code: int, sctid: int, active=True
) -> None:
    """An allergy whose fkmedicamento is not a drug, resolved to a substance"""
    session.execute(
        text(
            "INSERT INTO demo.alergia "
            "(fkpessoa, fkmedicamento, sctid, ativo, created_at, created_by) "
            "VALUES (:id_patient, :code, :sctid, :active, now(), 1)"
        ),
        {"id_patient": id_patient, "code": code, "sctid": sctid, "active": active},
    )
    session_commit()


def _create(drugs: list[dict]) -> tuple[int, list[int]]:
    """Creates a prescription with the given drugs (kwargs of
    create_prescription_drug minus the ids), returning its id and the
    prescription drug ids in the same order"""
    prescription = utils_test_prescription.create_basic_prescription()

    base_id = int(f"{prescription.id}010")
    for offset, drug in enumerate(drugs):
        utils_test_prescription.create_prescription_drug(
            id=base_id + offset, idPrescription=prescription.id, **drug
        )

    return prescription.id, [base_id + offset for offset in range(len(drugs))]


def _view(client, headers, id_prescription: int) -> dict:
    response = client.get(f"/prescriptions/{id_prescription}", headers=headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def _flag(id_prescription_drug: int) -> str | None:
    """presmed.alergia as stored"""
    return session.execute(
        text("SELECT alergia FROM demo.presmed WHERE fkpresmed = :id"),
        {"id": id_prescription_drug},
    ).scalar()


def _item(payload: dict, id_prescription_drug: int) -> dict:
    for item in payload["prescription"]:
        if item["idPrescriptionDrug"] == str(id_prescription_drug):
            return item

    raise AssertionError(f"prescribed drug {id_prescription_drug} is not listed")


def _why(payload: dict, id_prescription_drug: int) -> tuple:
    """Why the item was flagged or not, as the maintainers read it: the flag as
    it arrived and what the allergy records said of the item"""
    item = _item(payload, id_prescription_drug)
    return item["allergyFlag"], item["allergyRecord"]


def _has_allergy_alert(payload: dict, id_prescription_drug: int) -> bool:
    """Whether the item carries the alert and the payload flags it the same way"""
    alerted = any(
        a["type"] == "allergy" for a in _alerts_of(payload, id_prescription_drug)
    )
    assert _item(payload, id_prescription_drug)["allergy"] is alerted

    return alerted


def test_the_flag_stands_without_allergy_records(client, analyst_headers):
    """Clients without allergy records keep the integration flag"""
    id_prescription, (id_a,) = _create([{"idDrug": _DRUG_A[0], "allergy": "S"}])

    payload = _view(client, analyst_headers, id_prescription)

    assert _has_allergy_alert(payload, id_a) is True
    assert payload["alertStats"]["allergy"] == 1
    assert _why(payload, id_a) == ("S", None)


def test_an_inactivated_allergy_drops_the_flag(client, analyst_headers):
    """Flagged on arrival, inactivated afterwards: no longer an alert"""
    id_prescription, (id_a,) = _create([{"idDrug": _DRUG_A[0], "allergy": "S"}])
    _register_allergy(_SEED_PATIENT, _DRUG_A[0], active=False)

    payload = _view(client, analyst_headers, id_prescription)

    assert _flag(id_a) == "S"
    assert _has_allergy_alert(payload, id_a) is False
    assert payload["alertStats"].get("allergy", 0) == 0
    assert _why(payload, id_a) == ("S", "inactive")


def test_an_allergy_recorded_after_arrival_raises_the_alert(client, analyst_headers):
    """Not flagged on arrival, recorded afterwards for the same drug"""
    id_prescription, (id_a, id_b) = _create(
        [{"idDrug": _DRUG_A[0], "allergy": "N"}, {"idDrug": _DRUG_B[0]}]
    )
    _register_allergy(_SEED_PATIENT, _DRUG_A[0])

    payload = _view(client, analyst_headers, id_prescription)

    assert _flag(id_a) == "N"
    assert _has_allergy_alert(payload, id_a) is True
    assert _has_allergy_alert(payload, id_b) is False
    assert payload["alertStats"]["allergy"] == 1
    assert _why(payload, id_a) == ("N", "active")
    assert _why(payload, id_b) == ("N", None)


def test_an_allergy_resolved_by_substance_raises_the_alert(client, analyst_headers):
    """fkmedicamento references no drug: the record's sctid matches the item"""
    id_prescription, (id_a, id_b) = _create(
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}]
    )
    _register_allergy_by_substance(_SEED_PATIENT, _UNMAPPED_CODE, _SUBSTANCE_A[0])

    payload = _view(client, analyst_headers, id_prescription)

    assert _flag(id_a) == "N"
    assert _has_allergy_alert(payload, id_a) is True
    assert _has_allergy_alert(payload, id_b) is False
    assert _why(payload, id_a) == ("N", "active")


def test_an_allergy_inactivated_by_substance_drops_the_flag(client, analyst_headers):
    """Only the substance's records count: other allergies leave the flag as is"""
    id_prescription, (id_a, id_b) = _create(
        [
            {"idDrug": _DRUG_A[0], "allergy": "S"},
            {"idDrug": _DRUG_B[0], "allergy": "S"},
        ]
    )
    _register_allergy_by_substance(
        _SEED_PATIENT, _UNMAPPED_CODE, _SUBSTANCE_A[0], active=False
    )
    _register_allergy_by_substance(
        _SEED_PATIENT, _OTHER_UNMAPPED_CODE, _SUBSTANCE_ALLERGEN[0]
    )

    payload = _view(client, analyst_headers, id_prescription)

    assert _has_allergy_alert(payload, id_a) is False
    assert _has_allergy_alert(payload, id_b) is True


def test_an_allergy_resolved_by_substance_is_cross_checked(client, analyst_headers):
    """Cross reactivity reads the record's sctid as well"""
    _register_allergy_by_substance(
        _SEED_PATIENT, _UNMAPPED_CODE, _SUBSTANCE_ALLERGEN[0]
    )
    _add_relation(_SUBSTANCE_B[0], _SUBSTANCE_ALLERGEN[0], "rx", "high")
    id_prescription, (id_b,) = _create([{"idDrug": _DRUG_B[0]}])

    payload = _view(client, analyst_headers, id_prescription)

    assert _count(payload, "rx") == 1
    assert _SUBSTANCE_ALLERGEN[1] in _alerts_of(payload, id_b)[0]["text"]


def _register_allergy_by_name(id_patient: int, code: int, name: str) -> None:
    """An allergy recorded by name only: no drug, no substance"""
    session.execute(
        text(
            "INSERT INTO demo.alergia "
            "(fkpessoa, fkmedicamento, nome_medicamento, ativo, created_at, created_by) "
            "VALUES (:id_patient, :code, :name, true, now(), 1)"
        ),
        {"id_patient": id_patient, "code": code, "name": name},
    )
    session_commit()


def _listed_allergy_records(payload: dict) -> list[str]:
    """The allergy records the screen lists with the notes (source pep), of
    this module's fixtures only"""
    return [
        a["text"]
        for a in payload["notesAllergies"]
        if a["source"] == "pep" and a["text"].startswith("ZZTest")
    ]


def test_the_screen_lists_the_active_allergy_records(client, analyst_headers):
    """The records that confirm the alert are listed with the notes: active
    ones only, once per name, by substance (the record's sctid first) or by the
    name recorded"""
    _register_allergy(_SEED_PATIENT, _DRUG_A[0])
    # the same substance recorded again, by sctid
    _register_allergy_by_substance(_SEED_PATIENT, _UNMAPPED_CODE, _SUBSTANCE_A[0])
    _register_allergy_by_substance(
        _SEED_PATIENT, _OTHER_UNMAPPED_CODE, _SUBSTANCE_ALLERGEN[0]
    )
    _register_allergy(_SEED_PATIENT, _DRUG_B[0], active=False)
    _register_allergy_by_name(_SEED_PATIENT, 99103, "ZZTest Alergia Sem Cadastro")
    id_prescription, _ = _create([{"idDrug": _DRUG_A[0]}])

    payload = _view(client, analyst_headers, id_prescription)

    assert _listed_allergy_records(payload) == [
        "ZZTest Alergia Sem Cadastro",
        _SUBSTANCE_A[1],
        _SUBSTANCE_ALLERGEN[1],
    ]
