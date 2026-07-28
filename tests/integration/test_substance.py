"""Integration tests for the /substance/* endpoints (substance_service).

The seed database ships with empty ``public.substancia`` and ``public.classe``
tables, so a fixture seeds a small, distinctive set of rows (removed after the
test) to exercise the service behaviour.
"""

import pytest
from sqlalchemy import text

from tests.conftest import get_access, make_headers, session, session_commit

from security.role import Role

# Distinctive test ids. Substance ids >= 90000 are wiped by the session-scoped
# clean_test_artifacts fixture (see tests/conftest.py); the class rows are
# removed by the seed fixture below.
SUBSTANCE_ALPHA = 99001
SUBSTANCE_BETA = 99002
SUBSTANCE_INACTIVE = 99003

CLASS_PARENT = "ZZTPARENT"
CLASS_CHILD = "ZZTCHILD"

NAME_ALPHA = "zztest alpha substance"
NAME_BETA = "zztest beta substance"
NAME_INACTIVE = "zztest gamma inactive"


@pytest.fixture
def seed_substances():
    """Insert distinctive substance/class rows and remove them afterwards."""
    session.execute(
        text(
            "INSERT INTO public.classe (idclasse, idclassemae, nome) "
            "VALUES (:id, NULL, :nome)"
        ),
        {"id": CLASS_PARENT, "nome": "zztest parent class"},
    )
    session.execute(
        text(
            "INSERT INTO public.classe (idclasse, idclassemae, nome) "
            "VALUES (:id, :parent, :nome)"
        ),
        {"id": CLASS_CHILD, "parent": CLASS_PARENT, "nome": "zztest child class"},
    )

    rows = [
        (SUBSTANCE_ALPHA, NAME_ALPHA, CLASS_CHILD, True),
        (SUBSTANCE_BETA, NAME_BETA, CLASS_CHILD, True),
        (SUBSTANCE_INACTIVE, NAME_INACTIVE, CLASS_CHILD, False),
    ]
    for sctid, nome, idclasse, ativo in rows:
        session.execute(
            text(
                "INSERT INTO public.substancia (sctid, nome, idclasse, ativo, manejo) "
                "VALUES (:sctid, :nome, :idclasse, :ativo, CAST(:manejo AS jsonb))"
            ),
            {
                "sctid": sctid,
                "nome": nome,
                "idclasse": idclasse,
                "ativo": ativo,
                # only the alpha substance carries handling text
                "manejo": (
                    '{"allergy": "cuidado especial de alergia"}'
                    if sctid == SUBSTANCE_ALPHA
                    else None
                ),
            },
        )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM public.substancia WHERE sctid IN (:a, :b, :c)"),
        {"a": SUBSTANCE_ALPHA, "b": SUBSTANCE_BETA, "c": SUBSTANCE_INACTIVE},
    )
    session.execute(
        text("DELETE FROM public.classe WHERE idclasse IN (:a, :b)"),
        {"a": CLASS_PARENT, "b": CLASS_CHILD},
    )
    session_commit()


def _data(response):
    """Return the ``data`` payload of a successful response envelope."""
    return response.get_json()["data"]


def test_get_substances_requires_permission(client, seed_substances):
    """A user without READ_BASIC_FEATURES cannot list substances [401]."""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))
    response = client.get("/substance", headers=headers)

    assert response.status_code == 401


def test_get_substances_returns_seeded_rows(client, analyst_headers, seed_substances):
    """Listing returns the seeded substances with upper-cased names and string ids."""
    response = client.get("/substance", headers=analyst_headers)

    assert response.status_code == 200
    items = _data(response)
    match = next((i for i in items if i["sctid"] == str(SUBSTANCE_ALPHA)), None)
    assert match is not None, "seeded substance not present in listing"
    assert match["name"] == NAME_ALPHA.upper()
    assert match["idclass"] == CLASS_CHILD
    assert match["active"] is True


def test_get_substances_orders_active_before_inactive(
    client, analyst_headers, seed_substances
):
    """Active substances are ordered ahead of inactive ones."""
    response = client.get("/substance", headers=analyst_headers)

    items = _data(response)
    positions = {i["sctid"]: idx for idx, i in enumerate(items)}
    # the inactive substance must appear after both active ones
    assert positions[str(SUBSTANCE_INACTIVE)] > positions[str(SUBSTANCE_ALPHA)]
    assert positions[str(SUBSTANCE_INACTIVE)] > positions[str(SUBSTANCE_BETA)]


def test_find_substance_by_term(client, analyst_headers, seed_substances):
    """Searching by term returns matching substances sorted by name ascending."""
    response = client.get("/substance/find?term=zztest", headers=analyst_headers)

    assert response.status_code == 200
    items = _data(response)
    names = [i["name"] for i in items]
    # results are upper-cased and alpha sorts before beta
    assert NAME_ALPHA.upper() in names
    assert NAME_BETA.upper() in names
    assert names.index(NAME_ALPHA.upper()) < names.index(NAME_BETA.upper())


def test_find_substance_empty_term_is_rejected(client, analyst_headers):
    """An empty search term is a bad request [400]."""
    response = client.get("/substance/find?term=", headers=analyst_headers)

    assert response.status_code == 400


def test_resolve_substances_by_ids(client, analyst_headers, seed_substances):
    """Resolving by ids returns the matching substances only."""
    response = client.get(
        f"/substance/resolve?ids={SUBSTANCE_ALPHA},{SUBSTANCE_BETA}",
        headers=analyst_headers,
    )

    assert response.status_code == 200
    sctids = {i["sctid"] for i in _data(response)}
    assert sctids == {str(SUBSTANCE_ALPHA), str(SUBSTANCE_BETA)}


def test_resolve_substances_ignores_non_numeric_ids(
    client, analyst_headers, seed_substances
):
    """Non-numeric ids are discarded before querying (sctid is numeric)."""
    response = client.get(
        f"/substance/resolve?ids={SUBSTANCE_ALPHA},abc", headers=analyst_headers
    )

    assert response.status_code == 200
    sctids = {i["sctid"] for i in _data(response)}
    assert sctids == {str(SUBSTANCE_ALPHA)}


def test_resolve_substances_empty_returns_empty_list(client, analyst_headers):
    """An empty id list resolves to an empty result."""
    response = client.get("/substance/resolve?ids=", headers=analyst_headers)

    assert response.status_code == 200
    assert _data(response) == []


def test_get_substance_classes(client, analyst_headers, seed_substances):
    """Listing classes returns the seeded classes with upper-cased names."""
    response = client.get("/substance/class", headers=analyst_headers)

    assert response.status_code == 200
    by_id = {i["id"]: i for i in _data(response)}
    assert CLASS_CHILD in by_id
    assert by_id[CLASS_CHILD]["name"] == "zztest child class".upper()


def test_find_substance_class_resolves_parent_name(
    client, analyst_headers, seed_substances
):
    """Searching classes exposes the parent class name for a child class."""
    response = client.get(
        "/substance/class/find?term=zztest child", headers=analyst_headers
    )

    assert response.status_code == 200
    match = next((i for i in _data(response) if i["id"] == CLASS_CHILD), None)
    assert match is not None
    assert match["parent"] == "zztest parent class"


def test_find_substance_class_empty_term_is_rejected(client, analyst_headers):
    """An empty class search term is a bad request [400]."""
    response = client.get("/substance/class/find?term=", headers=analyst_headers)

    assert response.status_code == 400


def test_resolve_substance_classes_by_ids(client, analyst_headers, seed_substances):
    """Resolving classes by ids returns them together with their parent name."""
    response = client.get(
        f"/substance/class/resolve?ids={CLASS_CHILD}", headers=analyst_headers
    )

    assert response.status_code == 200
    match = next((i for i in _data(response) if i["id"] == CLASS_CHILD), None)
    assert match is not None
    assert match["parent"] == "zztest parent class"


def test_substance_handling_returns_text(client, analyst_headers, seed_substances):
    """A substance with handling text for the alert type returns that text."""
    response = client.get(
        f"/substance/handling?sctid={SUBSTANCE_ALPHA}&alertType=allergy",
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert "cuidado" in str(_data(response))


def test_substance_handling_missing_returns_none(
    client, analyst_headers, seed_substances
):
    """A substance without handling text for the alert type returns null data."""
    response = client.get(
        f"/substance/handling?sctid={SUBSTANCE_BETA}&alertType=allergy",
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert _data(response) is None
