"""Integration tests for the protocol drug search and resolution feature.

Three endpoints back the drug picker used when a protocol condition targets
specific drugs:

- ``GET /drugs/find``        searches by name, restricted to drugs that have
                            outliers (i.e. drugs the scoring pipeline knows).
- ``GET /drugs/resolve``     turns a list of already-picked ids back into
                            names, with no outlier restriction.
- ``GET /drugs/frequencies`` lists the frequencies available to the schema.

The outlier restriction on ``find`` and its absence on ``resolve`` are the two
behaviours that matter most here: a drug that stopped being scored must remain
resolvable, otherwise a saved protocol would render with a blank drug.
"""

import pytest
from sqlalchemy import text

from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

FIND_URL = "/drugs/find"
RESOLVE_URL = "/drugs/resolve"
FREQUENCIES_URL = "/drugs/frequencies"

# unit-conversion/test drug ids use >= 90000
DRUG_WITHOUT_OUTLIER = 90001
DRUG_WITH_OUTLIER = 90002

DRUG_WITHOUT_OUTLIER_NAME = "ZZTEST BUSCA SEM OUTLIER"
DRUG_WITH_OUTLIER_NAME = "ZZTEST BUSCA COM OUTLIER"
TEST_DRUG_TERM = "ZZTEST BUSCA"

# seed drugs, all of them scored (present in the outlier table)
SEED_DRUG_ALOPURINOL = 2
SEED_DRUG_PARACETAMOL = 15
SEED_DRUG_OMEPRAZOL = 24
SEED_DRUG_OMEPRAZOL_NAME = "OMEPRAZOL 20mg CP"

INVALID_DRUG_ID = 999999


@pytest.fixture
def dispensing_headers(client):
    """Headers with DISPENSING_MANAGER role — has neither READ_BASIC_FEATURES nor READ_PRESCRIPTION"""
    return make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))


@pytest.fixture
def search_drugs():
    """Two drugs with the same name prefix, only one of them scored"""
    for id, name in (
        (DRUG_WITHOUT_OUTLIER, DRUG_WITHOUT_OUTLIER_NAME),
        (DRUG_WITH_OUTLIER, DRUG_WITH_OUTLIER_NAME),
    ):
        session.execute(
            text(
                "INSERT INTO demo.medicamento (fkmedicamento, fkhospital, nome) "
                "VALUES (:id, 1, :name)"
            ),
            {"id": id, "name": name},
        )

    session.execute(
        text(
            "INSERT INTO demo.outlier "
            "(fkmedicamento, idsegmento, contagem, doseconv, frequenciadia, escore) "
            "VALUES (:id, 1, 10, 1, 1, 1)"
        ),
        {"id": DRUG_WITH_OUTLIER},
    )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM demo.outlier WHERE fkmedicamento >= 90000"),
    )
    session.execute(
        text("DELETE FROM demo.medicamento WHERE fkmedicamento >= 90000"),
    )
    session_commit()


def _names(data):
    """Drug names of a search/resolve response, in response order"""
    return [item["name"] for item in data]


def test_find_no_token(client):
    """GET /drugs/find — returns 401 without authentication"""
    response = client.get(f"{FIND_URL}?term=omeprazol")

    assert response.status_code == 401


def test_find_permission_denied(client, dispensing_headers):
    """GET /drugs/find — returns 401 for a role without READ_BASIC_FEATURES"""
    response = client.get(f"{FIND_URL}?term=omeprazol", headers=dispensing_headers)

    assert response.status_code == 401


def test_find_empty_term(client, analyst_headers):
    """GET /drugs/find — returns 400 when the term is empty"""
    response = client.get(f"{FIND_URL}?term=", headers=analyst_headers)

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.invalidParams"


def test_find_missing_term(client, analyst_headers):
    """GET /drugs/find — returns 400 when the term parameter is absent"""
    response = client.get(FIND_URL, headers=analyst_headers)

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.invalidParams"


def test_find_is_case_insensitive_and_partial(client, analyst_headers):
    """GET /drugs/find — matches part of the name regardless of case"""
    response = client.get(f"{FIND_URL}?term=omeprazol", headers=analyst_headers)

    assert response.status_code == 200

    data = response.get_json()["data"]
    assert {
        "idDrug": str(SEED_DRUG_OMEPRAZOL),
        "name": SEED_DRUG_OMEPRAZOL_NAME,
    } in data


def test_find_returns_results_sorted_by_name(client, analyst_headers):
    """GET /drugs/find — returns the matches sorted by name"""
    response = client.get(f"{FIND_URL}?term=CP", headers=analyst_headers)

    assert response.status_code == 200

    names = _names(response.get_json()["data"])
    assert len(names) > 1
    assert names == sorted(names)


def test_find_only_returns_scored_drugs(client, analyst_headers, search_drugs):
    """GET /drugs/find — a drug without outliers is not searchable"""
    response = client.get(f"{FIND_URL}?term={TEST_DRUG_TERM}", headers=analyst_headers)

    assert response.status_code == 200

    data = response.get_json()["data"]
    assert data == [{"idDrug": str(DRUG_WITH_OUTLIER), "name": DRUG_WITH_OUTLIER_NAME}]


def test_find_without_matches(client, analyst_headers):
    """GET /drugs/find — returns an empty list when nothing matches"""
    response = client.get(
        f"{FIND_URL}?term=ZZTEST INEXISTENTE", headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_resolve_no_token(client):
    """GET /drugs/resolve — returns 401 without authentication"""
    response = client.get(f"{RESOLVE_URL}?ids={SEED_DRUG_OMEPRAZOL}")

    assert response.status_code == 401


def test_resolve_permission_denied(client, dispensing_headers):
    """GET /drugs/resolve — returns 401 for a role without READ_BASIC_FEATURES"""
    response = client.get(
        f"{RESOLVE_URL}?ids={SEED_DRUG_OMEPRAZOL}", headers=dispensing_headers
    )

    assert response.status_code == 401


def test_resolve_without_ids(client, analyst_headers):
    """GET /drugs/resolve — returns an empty list when no id is given"""
    response = client.get(f"{RESOLVE_URL}?ids=", headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_resolve_ignores_non_numeric_ids(client, analyst_headers):
    """GET /drugs/resolve — a non-numeric id resolves to nothing instead of failing"""
    response = client.get(f"{RESOLVE_URL}?ids=abc,-,1.5", headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_resolve_mixes_valid_and_invalid_ids(client, analyst_headers):
    """GET /drugs/resolve — resolves the numeric ids and drops the rest"""
    response = client.get(
        f"{RESOLVE_URL}?ids=abc,{SEED_DRUG_OMEPRAZOL},{INVALID_DRUG_ID}",
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == [
        {"idDrug": str(SEED_DRUG_OMEPRAZOL), "name": SEED_DRUG_OMEPRAZOL_NAME}
    ]


def test_resolve_returns_names_sorted_by_name(client, analyst_headers):
    """GET /drugs/resolve — returns the drugs sorted by name, not in the requested order"""
    ids = f"{SEED_DRUG_OMEPRAZOL},{SEED_DRUG_ALOPURINOL},{SEED_DRUG_PARACETAMOL}"
    response = client.get(f"{RESOLVE_URL}?ids={ids}", headers=analyst_headers)

    assert response.status_code == 200

    data = response.get_json()["data"]
    assert len(data) == 3
    assert _names(data) == sorted(_names(data))
    assert [item["idDrug"] for item in data] == [
        str(SEED_DRUG_ALOPURINOL),
        str(SEED_DRUG_OMEPRAZOL),
        str(SEED_DRUG_PARACETAMOL),
    ]


def test_resolve_returns_drugs_without_outliers(client, analyst_headers, search_drugs):
    """GET /drugs/resolve — resolves a drug without outliers, which find() would not return"""
    response = client.get(
        f"{RESOLVE_URL}?ids={DRUG_WITHOUT_OUTLIER}", headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == [
        {"idDrug": str(DRUG_WITHOUT_OUTLIER), "name": DRUG_WITHOUT_OUTLIER_NAME}
    ]


def test_frequencies_no_token(client):
    """GET /drugs/frequencies — returns 401 without authentication"""
    response = client.get(FREQUENCIES_URL)

    assert response.status_code == 401


def test_frequencies_permission_denied(client, dispensing_headers):
    """GET /drugs/frequencies — returns 401 for a role without READ_PRESCRIPTION"""
    response = client.get(FREQUENCIES_URL, headers=dispensing_headers)

    assert response.status_code == 401


def test_frequencies_list(client, analyst_headers):
    """GET /drugs/frequencies — lists every distinct frequency of the schema, sorted by description"""
    response = client.get(FREQUENCIES_URL, headers=analyst_headers)

    assert response.status_code == 200

    data = response.get_json()["data"]
    expected = session.execute(
        text("SELECT DISTINCT fkfrequencia, nome FROM demo.frequencia ORDER BY nome")
    ).fetchall()

    assert len(data) == len(expected)
    assert data == [{"id": row[0], "description": row[1]} for row in expected]
