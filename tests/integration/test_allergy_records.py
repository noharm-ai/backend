"""Integration tests for the allergy records of a patient
(``GET /prescriptions/<id>/allergy-records``, allergy_service).

Lists every alergia row of the prescription's patient for maintainers.
fkmedicamento does not always reference a medicamento record: when it does,
the record shows the drug and the substance of its sctid; when it does not,
the record's own name and sctid stand alone.

Substances and drugs come from the fixtures of
``test_prescription_interactions.py`` and are removed by them.
"""

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.integration.test_prescription_interactions import (  # noqa: F401
    _DRUG_ALLERGEN,
    _SEED_PATIENT,
    _SUBSTANCE_ALLERGEN,
    _SUBSTANCE_B,
    _register_allergy,
    seed_substances_and_drugs,
)
from tests.utils import utils_test_prescription

# fkmedicamento with no medicamento record
_DANGLING_DRUG = 90199
# sctid with no substancia record
_UNKNOWN_SCTID = 90999
_FREE_TEXT_NAME = "ZZTest Alergia Texto Livre"
_NO_DRUG_NAME = "ZZTest Alergia Sem Medicamento"

pytestmark = pytest.mark.usefixtures("seed_substances_and_drugs")


@pytest.fixture(autouse=True)
def _clear_null_drug_records():
    """Rows without fkmedicamento escape the cleanup of the seed fixture."""
    yield
    session.execute(
        text("DELETE FROM demo.alergia WHERE nome_medicamento LIKE 'ZZTest%'")
    )
    session_commit()


def _register_record(id_drug: int | None, name: str, sctid: int | None) -> None:
    session.execute(
        text(
            "INSERT INTO demo.alergia "
            "(fkpessoa, fkmedicamento, nome_medicamento, sctid, ativo, "
            "created_at, created_by) "
            "VALUES (:id_patient, :id_drug, :name, :sctid, true, now(), 1)"
        ),
        {"id_patient": _SEED_PATIENT, "id_drug": id_drug, "name": name, "sctid": sctid},
    )
    session_commit()


def _url(id_prescription: int) -> str:
    return f"/prescriptions/{id_prescription}/allergy-records"


def _records(client, headers) -> list[dict]:
    """The records this module created (the seed patient may hold others)."""
    prescription = utils_test_prescription.create_basic_prescription()

    response = client.get(_url(prescription.id), headers=headers)
    assert response.status_code == 200, response.get_json()

    return [
        r
        for r in response.get_json()["data"]
        if (r["idDrug"] and int(r["idDrug"]) >= 90000)
        or (r["drugName"] or "").startswith("ZZTest")
    ]


def test_only_maintainers_list_the_records(client, analyst_headers):
    """A pharmacist sees the allergies on the screen, not the raw records."""
    prescription = utils_test_prescription.create_basic_prescription()

    response = client.get(_url(prescription.id), headers=analyst_headers)

    assert response.status_code == 401


def test_unknown_prescription(client, curator_headers):
    response = client.get(_url(999999999), headers=curator_headers)

    assert response.status_code == 400


def test_a_record_of_a_catalogued_drug_shows_the_drug_substance(
    client, curator_headers
):
    _register_allergy(_SEED_PATIENT, _DRUG_ALLERGEN[0])

    (record,) = _records(client, curator_headers)

    assert record["idDrug"] == str(_DRUG_ALLERGEN[0])
    assert record["drug"] == {
        "name": _DRUG_ALLERGEN[1],
        "sctid": str(_SUBSTANCE_ALLERGEN[0]),
        "substance": _SUBSTANCE_ALLERGEN[1],
    }
    assert record["active"] is True
    assert record["createdAt"] is not None


def test_a_record_without_drug_shows_its_own_name_and_substance(
    client, curator_headers
):
    """fkmedicamento points at no medicamento: the record stands alone."""
    _register_record(_DANGLING_DRUG, _FREE_TEXT_NAME, _SUBSTANCE_B[0])
    _register_record(None, _NO_DRUG_NAME, _UNKNOWN_SCTID)

    records = {r["drugName"]: r for r in _records(client, curator_headers)}

    dangling = records[_FREE_TEXT_NAME]
    assert dangling["idDrug"] == str(_DANGLING_DRUG)
    assert dangling["drug"] is None
    assert dangling["sctid"] == str(_SUBSTANCE_B[0])
    assert dangling["substance"] == _SUBSTANCE_B[1]

    no_drug = records[_NO_DRUG_NAME]
    assert no_drug["idDrug"] is None
    assert no_drug["drug"] is None
    # a sctid with no substance is still listed, so the gap shows
    assert no_drug["sctid"] == str(_UNKNOWN_SCTID)
    assert no_drug["substance"] is None


def test_inactive_records_are_listed_after_the_active(client, curator_headers):
    _register_allergy(_SEED_PATIENT, _DRUG_ALLERGEN[0], active=False)
    _register_record(_DANGLING_DRUG, _FREE_TEXT_NAME, None)

    records = _records(client, curator_headers)

    assert [r["active"] for r in records] == [True, False]
    assert records[1]["idDrug"] == str(_DRUG_ALLERGEN[0])
