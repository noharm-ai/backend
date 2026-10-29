"""Integration tests for the allergy records of a patient
(``GET /prescriptions/<id>/allergy-records``, allergy_service).

Lists every alergia row of the prescription's patient for maintainers.
fkmedicamento does not always reference a medicamento record: when it does,
the record shows the drug and the substance of its sctid; when it does not,
the record's own name and sctid stand alone.

Substances and drugs come from the fixtures of
``test_prescription_interactions.py`` and are removed by them.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text

from repository import culture_drug_repository
from tests.conftest import session, session_commit
from tests.integration.test_prescription_interactions import (  # noqa: F401
    _DRUG_ALLERGEN,
    _SEED_PATIENT,
    _SUBSTANCE_A,
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
# a patient with no prescription, to see the substance change in every patient
_OTHER_PATIENT = 90001
_SUBSTANCE_URL = "/allergy-records/substance"

pytestmark = pytest.mark.usefixtures("seed_substances_and_drugs")


@pytest.fixture(autouse=True)
def _clear_null_drug_records():
    """Rows without fkmedicamento escape the cleanup of the seed fixture."""
    yield
    session.execute(
        text("DELETE FROM demo.alergia WHERE nome_medicamento LIKE 'ZZTest%'")
    )
    session_commit()


def _register_record(
    id_drug: int | None,
    name: str | None,
    sctid: int | None,
    id_patient: int = _SEED_PATIENT,
) -> None:
    session.execute(
        text(
            "INSERT INTO demo.alergia "
            "(fkpessoa, fkmedicamento, nome_medicamento, sctid, ativo, "
            "created_at, created_by) "
            "VALUES (:id_patient, :id_drug, :name, :sctid, true, now(), 1)"
        ),
        {"id_patient": id_patient, "id_drug": id_drug, "name": name, "sctid": sctid},
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


@pytest.fixture
def mapping_writes(monkeypatch):
    """The drug name -> sctid mapping writes (DynamoDB), captured."""
    writes = []
    monkeypatch.setattr(
        culture_drug_repository, "put_sctid", lambda **kwargs: writes.append(kwargs)
    )
    return writes


def _sctids(id_drug: int | None, name: str | None) -> dict[int, int | None]:
    """The sctid of the records with the given drug and name, by patient."""
    session_commit()
    rows = session.execute(
        text(
            "SELECT fkpessoa, sctid FROM demo.alergia "
            "WHERE fkmedicamento IS NOT DISTINCT FROM :id_drug "
            "AND nome_medicamento IS NOT DISTINCT FROM :name"
        ),
        {"id_drug": id_drug, "name": name},
    ).fetchall()
    return {row.fkpessoa: row.sctid for row in rows}


def _set_substance(client, headers, **body):
    return client.put(_SUBSTANCE_URL, json=body, headers=headers)


def test_only_maintainers_set_the_substance(client, analyst_headers, mapping_writes):
    _register_record(_DANGLING_DRUG, _FREE_TEXT_NAME, None)

    response = _set_substance(
        client,
        analyst_headers,
        idDrug=_DANGLING_DRUG,
        drugName=_FREE_TEXT_NAME,
        sctid=_SUBSTANCE_B[0],
    )

    assert response.status_code == 401
    assert _sctids(_DANGLING_DRUG, _FREE_TEXT_NAME) == {_SEED_PATIENT: None}
    assert mapping_writes == []


def test_the_substance_of_a_catalogued_drug_is_not_set_here(
    client, curator_headers, mapping_writes
):
    """The substance of the record comes from the drug."""
    _register_allergy(_SEED_PATIENT, _DRUG_ALLERGEN[0])

    response = _set_substance(
        client, curator_headers, idDrug=_DRUG_ALLERGEN[0], sctid=_SUBSTANCE_B[0]
    )

    assert response.status_code == 400
    assert mapping_writes == []


def test_an_unknown_substance_is_refused(client, curator_headers, mapping_writes):
    _register_record(_DANGLING_DRUG, _FREE_TEXT_NAME, None)

    response = _set_substance(
        client,
        curator_headers,
        idDrug=_DANGLING_DRUG,
        drugName=_FREE_TEXT_NAME,
        sctid=_UNKNOWN_SCTID,
    )

    assert response.status_code == 400
    assert _sctids(_DANGLING_DRUG, _FREE_TEXT_NAME) == {_SEED_PATIENT: None}
    assert mapping_writes == []


def test_the_substance_is_set_on_every_record_of_the_drug_name(
    client, curator_headers, mapping_writes
):
    """Every patient's record with the same fkmedicamento and name changes,
    and the name is mapped to the substance for the records still to come."""
    _register_record(_DANGLING_DRUG, _FREE_TEXT_NAME, _SUBSTANCE_A[0])
    _register_record(_DANGLING_DRUG, _FREE_TEXT_NAME, None, id_patient=_OTHER_PATIENT)
    # same name, other fkmedicamento: another record
    _register_record(None, _FREE_TEXT_NAME, _SUBSTANCE_A[0])

    response = _set_substance(
        client,
        curator_headers,
        idDrug=str(_DANGLING_DRUG),
        drugName=_FREE_TEXT_NAME,
        sctid=str(_SUBSTANCE_B[0]),
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"] == {"updated": 2}
    assert _sctids(_DANGLING_DRUG, _FREE_TEXT_NAME) == {
        _SEED_PATIENT: _SUBSTANCE_B[0],
        _OTHER_PATIENT: _SUBSTANCE_B[0],
    }
    assert _sctids(None, _FREE_TEXT_NAME) == {_SEED_PATIENT: _SUBSTANCE_A[0]}
    assert mapping_writes == [
        {"name": _FREE_TEXT_NAME, "sctid": _SUBSTANCE_B[0], "idclass": None}
    ]


def test_a_record_without_fkmedicamento(client, curator_headers, mapping_writes):
    _register_record(None, _NO_DRUG_NAME, None)

    response = _set_substance(
        client,
        curator_headers,
        idDrug=None,
        drugName=_NO_DRUG_NAME,
        sctid=_SUBSTANCE_B[0],
    )

    assert response.status_code == 200, response.get_json()
    assert _sctids(None, _NO_DRUG_NAME) == {_SEED_PATIENT: _SUBSTANCE_B[0]}
    assert [w["name"] for w in mapping_writes] == [_NO_DRUG_NAME]


def test_a_record_without_name_is_not_mapped(client, curator_headers, mapping_writes):
    """There is no name to map: only the records change."""
    _register_record(_DANGLING_DRUG, None, None)

    response = _set_substance(
        client, curator_headers, idDrug=_DANGLING_DRUG, sctid=_SUBSTANCE_B[0]
    )

    assert response.status_code == 200, response.get_json()
    assert _sctids(_DANGLING_DRUG, None) == {_SEED_PATIENT: _SUBSTANCE_B[0]}
    assert mapping_writes == []


def test_a_missing_record_is_refused(client, curator_headers, mapping_writes):
    response = _set_substance(
        client,
        curator_headers,
        idDrug=_DANGLING_DRUG,
        drugName=_FREE_TEXT_NAME,
        sctid=_SUBSTANCE_B[0],
    )

    assert response.status_code == 400
    assert mapping_writes == []


def test_the_mapping_entry(monkeypatch):
    """Same key and attributes as the entries backend-private writes."""
    items = []

    class _Table:
        def put_item(self, Item):
            items.append(Item)

    class _Resource:
        def Table(self, name):
            assert name == "noharm_cultura_medicamento_sctid"
            return _Table()

    monkeypatch.setattr(
        culture_drug_repository.aws, "get_resource", lambda *a, **k: _Resource()
    )

    culture_drug_repository.put_sctid(
        name="  Dipirona   sódica  gotas ", sctid=90102, idclass="J01"
    )

    (item,) = items
    assert item["nome"] == "DIPIRONA SODICA GOTAS"
    assert item["nome_original"] == "Dipirona   sódica  gotas"
    assert item["sctid"] == Decimal(90102)
    assert item["idclasse"] == "J01"
    assert item["origem"] == "manual"
    assert item["probabilidade"] is None
    assert item["atualizado_em"]


def test_the_substance_is_removed_from_every_record_of_the_drug_name(
    client, curator_headers, mapping_writes
):
    """The name stays mapped, to no substance, so backend-private does not
    infer one again."""
    _register_record(_DANGLING_DRUG, _FREE_TEXT_NAME, _SUBSTANCE_A[0])
    _register_record(
        _DANGLING_DRUG, _FREE_TEXT_NAME, _SUBSTANCE_A[0], id_patient=_OTHER_PATIENT
    )

    response = _set_substance(
        client,
        curator_headers,
        idDrug=_DANGLING_DRUG,
        drugName=_FREE_TEXT_NAME,
        sctid=None,
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"] == {"updated": 2}
    assert _sctids(_DANGLING_DRUG, _FREE_TEXT_NAME) == {
        _SEED_PATIENT: None,
        _OTHER_PATIENT: None,
    }
    assert mapping_writes == [{"name": _FREE_TEXT_NAME, "sctid": None, "idclass": None}]


def test_the_mapping_entry_without_substance(monkeypatch):
    items = []

    class _Table:
        def put_item(self, Item):
            items.append(Item)

    class _Resource:
        def Table(self, name):
            return _Table()

    monkeypatch.setattr(
        culture_drug_repository.aws, "get_resource", lambda *a, **k: _Resource()
    )

    culture_drug_repository.put_sctid(name="Contraste", sctid=None, idclass=None)

    (item,) = items
    assert item["nome"] == "CONTRASTE"
    assert item["sctid"] is None
    assert item["idclasse"] is None
    assert item["origem"] == "manual"
