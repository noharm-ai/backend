"""Integration tests for the /admin/global-memory endpoints.

Covers admin_global_memory_service: the kind-filtered listing and the update
routine that keeps a "<kind>_bkp" snapshot of the previous value. Records live
in the shared public.memoria table, so every row created here uses a kind
starting with the reserved prefix below.
"""

import json

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from utils import status

LIST_URL = "/admin/global-memory/list"
UPDATE_URL = "/admin/global-memory/update"

# every kind written by this module starts with this prefix, so a single
# LIKE clause isolates the rows (including the "_bkp" snapshots)
_PREFIX = "zztest-gm"

_ALPHA_KIND = f"{_PREFIX}-alpha"
_BETA_KIND = f"{_PREFIX}-beta"
_GAMMA_KIND = f"{_PREFIX}-gamma"

_ALPHA_VALUE = {"label": "alpha", "enabled": True}
_BETA_VALUE = {"label": "beta", "items": [1, 2, 3]}
_GAMMA_VALUE = {"label": "gamma"}

# public.usuario id of the user behind the admin_headers fixture
_ADMIN_USER_ID = 2


def _insert(kind: str, value: dict) -> int:
    """Insert a global memory row and return its generated key."""
    result = session.execute(
        text(
            "INSERT INTO public.memoria (tipo, valor, update_at, update_by) "
            "VALUES (:kind, CAST(:value AS json), now(), 1) RETURNING idmemoria"
        ),
        {"kind": kind, "value": json.dumps(value)},
    )
    return result.scalar()


def _rows(kind: str):
    """Return (value, update_by) for every row of a given kind."""
    result = session.execute(
        text(
            "SELECT valor, update_by FROM public.memoria WHERE tipo = :kind "
            "ORDER BY idmemoria"
        ),
        {"kind": kind},
    )
    return result.all()


def _cleanup():
    """Remove every row this module may have created."""
    session.execute(
        text("DELETE FROM public.memoria WHERE tipo LIKE :prefix"),
        {"prefix": f"{_PREFIX}%"},
    )
    session_commit()


@pytest.fixture(autouse=True)
def seed_global_memory():
    """Recreate the reserved rows before each test and drop them afterwards."""
    _cleanup()

    keys = {
        _ALPHA_KIND: _insert(_ALPHA_KIND, _ALPHA_VALUE),
        _BETA_KIND: _insert(_BETA_KIND, _BETA_VALUE),
        _GAMMA_KIND: _insert(_GAMMA_KIND, _GAMMA_VALUE),
    }
    session_commit()

    yield keys

    _cleanup()


def _list(client, headers, kinds):
    """Call the listing endpoint with the given kinds."""
    return client.post(LIST_URL, data=json.dumps({"kinds": kinds}), headers=headers)


def _update(client, headers, key, kind, value):
    """Call the update endpoint."""
    return client.post(
        UPDATE_URL,
        data=json.dumps({"key": key, "kind": kind, "value": value}),
        headers=headers,
    )


def test_list_requires_admin_permission(client, analyst_headers):
    """Listing global memory without ADMIN_NZERO is refused [401 UNAUTHORIZED]."""
    response = _list(client, analyst_headers, [_ALPHA_KIND])

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_is_refused_for_curator(client, curator_headers):
    """CURATOR is a privileged role but still lacks ADMIN_NZERO [401 UNAUTHORIZED]."""
    response = _list(client, curator_headers, [_ALPHA_KIND])

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_returns_key_kind_and_value(client, admin_headers, seed_global_memory):
    """A listed entry carries its key, its kind and the stored json value."""
    response = _list(client, admin_headers, [_ALPHA_KIND])

    assert response.status_code == status.HTTP_200_OK
    items = response.get_json()["data"]
    assert len(items) == 1
    assert items[0]["key"] == seed_global_memory[_ALPHA_KIND]
    assert items[0]["kind"] == _ALPHA_KIND
    assert items[0]["value"] == _ALPHA_VALUE


def test_list_returns_only_the_requested_kinds(client, admin_headers):
    """The kinds filter narrows the result to the requested kinds."""
    response = _list(client, admin_headers, [_ALPHA_KIND, _BETA_KIND])

    assert response.status_code == status.HTTP_200_OK
    kinds = {item["kind"] for item in response.get_json()["data"]}
    assert kinds == {_ALPHA_KIND, _BETA_KIND}


def test_list_unknown_kind_returns_empty(client, admin_headers):
    """Asking for a kind that does not exist returns an empty list."""
    response = _list(client, admin_headers, [f"{_PREFIX}-does-not-exist"])

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == []


def test_list_rejects_missing_kinds(client, admin_headers):
    """The kinds attribute is mandatory [400 BAD REQUEST]."""
    response = client.post(LIST_URL, data=json.dumps({}), headers=admin_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_update_replaces_the_value(client, admin_headers, seed_global_memory):
    """Updating stores the new value and returns the updated key."""
    key = seed_global_memory[_ALPHA_KIND]
    new_value = {"label": "alpha updated", "enabled": False}

    response = _update(client, admin_headers, key, _ALPHA_KIND, new_value)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == str(key)

    session_commit()
    rows = _rows(_ALPHA_KIND)
    assert len(rows) == 1
    assert rows[0][0] == new_value


def test_update_stamps_the_current_user(client, admin_headers, seed_global_memory):
    """The updated row records the user who performed the change."""
    key = seed_global_memory[_BETA_KIND]

    response = _update(client, admin_headers, key, _BETA_KIND, {"label": "beta v2"})

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    rows = _rows(_BETA_KIND)
    assert rows[0][1] == _ADMIN_USER_ID


def test_update_keeps_a_backup_of_the_previous_value(
    client, admin_headers, seed_global_memory
):
    """The previous value is preserved in a row whose kind ends with _bkp."""
    key = seed_global_memory[_GAMMA_KIND]

    response = _update(client, admin_headers, key, _GAMMA_KIND, {"label": "gamma v2"})

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    backup = _rows(f"{_GAMMA_KIND}_bkp")
    assert len(backup) == 1
    assert backup[0][0] == _GAMMA_VALUE
    # the snapshot keeps the authorship of the value it holds
    assert backup[0][1] == 1


def test_update_backup_is_not_returned_by_the_listing(
    client, admin_headers, seed_global_memory
):
    """The _bkp snapshot is a separate kind and is not listed with the original."""
    key = seed_global_memory[_ALPHA_KIND]
    _update(client, admin_headers, key, _ALPHA_KIND, {"label": "alpha v2"})

    response = _list(client, admin_headers, [_ALPHA_KIND])

    assert response.status_code == status.HTTP_200_OK
    items = response.get_json()["data"]
    assert len(items) == 1
    assert items[0]["value"] == {"label": "alpha v2"}


def test_update_unknown_key_is_refused(client, admin_headers):
    """Updating a key that does not exist is a business error [400 BAD REQUEST]."""
    response = _update(client, admin_headers, 99999999, _ALPHA_KIND, {"label": "x"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"


def test_update_requires_admin_permission(client, analyst_headers, seed_global_memory):
    """Updating global memory without ADMIN_NZERO is refused [401 UNAUTHORIZED]."""
    key = seed_global_memory[_ALPHA_KIND]

    response = _update(client, analyst_headers, key, _ALPHA_KIND, {"label": "x"})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    session_commit()
    assert _rows(_ALPHA_KIND)[0][0] == _ALPHA_VALUE


def test_update_rejects_a_non_object_value(client, admin_headers, seed_global_memory):
    """The value must be a json object [400 BAD REQUEST]."""
    key = seed_global_memory[_ALPHA_KIND]

    response = _update(client, admin_headers, key, _ALPHA_KIND, "not-an-object")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
