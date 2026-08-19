"""Integration tests for the /admin/memory endpoints.

Covers admin_memory_service: the kind-filtered listing (including the
placeholder rows returned for kinds that have no record yet and the
"map-schedules" values derived from recent prescriptions) and the update
routine that keeps a "<kind>_bkp" snapshot and guards the protected feature
flags.

Records live in the schema-local demo.memoria table. Every row created here
uses a kind starting with the reserved prefix below, except the tests that
must target the real "features" kind — those snapshot the seed value and
restore it afterwards.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import FeatureEnum, MemoryEnum
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from utils import status

LIST_URL = "/admin/memory/list"
UPDATE_URL = "/admin/memory"

# every kind written by this module starts with this prefix, so a single
# LIKE clause isolates the rows (including the "_bkp" snapshots)
_PREFIX = "zztest-am"

_ALPHA_KIND = f"{_PREFIX}-alpha"
_BETA_KIND = f"{_PREFIX}-beta"

_ALPHA_VALUE = {"label": "alpha", "enabled": True}
_BETA_VALUE = ["one", "two"]

_FEATURES_KIND = MemoryEnum.FEATURES.value
_SCHEDULES_KIND = MemoryEnum.MAP_SCHEDULES.value

# public.usuario id of the users behind the admin_headers/curator_headers fixtures
_ADMIN_USER_ID = 2
_CURATOR_USER_ID = 3

# id of the user that owns the seeded rows created by this module
_SEED_USER_ID = 1


def _insert(kind: str, value) -> int:
    """Insert a schema memory row and return its generated key."""
    result = session.execute(
        text(
            "INSERT INTO demo.memoria (tipo, valor, update_at, update_by) "
            "VALUES (:kind, CAST(:value AS json), now(), :user) RETURNING idmemoria"
        ),
        {"kind": kind, "value": json.dumps(value), "user": _SEED_USER_ID},
    )
    return result.scalar()


def _rows(kind: str):
    """Return (key, value, update_by) for every row of a given kind."""
    result = session.execute(
        text(
            "SELECT idmemoria, valor, update_by FROM demo.memoria WHERE tipo = :kind "
            "ORDER BY idmemoria"
        ),
        {"kind": kind},
    )
    return result.all()


def _cleanup():
    """Remove every reserved row this module may have created."""
    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo LIKE :prefix"),
        {"prefix": f"{_PREFIX}%"},
    )
    session_commit()


@pytest.fixture(autouse=True)
def seed_memory():
    """Recreate the reserved rows before each test and drop them afterwards."""
    _cleanup()

    keys = {
        _ALPHA_KIND: _insert(_ALPHA_KIND, _ALPHA_VALUE),
        _BETA_KIND: _insert(_BETA_KIND, _BETA_VALUE),
    }
    session_commit()

    yield keys

    _cleanup()


@pytest.fixture
def features_row():
    """Snapshot the seeded "features" row and restore it after the test.

    The features kind is shared seed data consumed by other suites, and
    updating it also leaves a "features_bkp" snapshot behind, so both are
    reverted here.
    """
    original = _rows(_FEATURES_KIND)
    assert len(original) == 1, "the demo schema is expected to seed one features row"
    key, value, user = original[0]

    yield {"key": key, "value": value, "user": user}

    session.execute(
        text(
            "UPDATE demo.memoria SET valor = CAST(:value AS json), update_by = :user "
            "WHERE idmemoria = :key AND tipo = :kind"
        ),
        {
            "value": json.dumps(value),
            "user": user,
            "key": key,
            "kind": _FEATURES_KIND,
        },
    )
    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo = :kind"),
        {"kind": f"{_FEATURES_KIND}_bkp"},
    )
    session_commit()


def _list(client, headers, kinds):
    """Call the listing endpoint with the given kinds."""
    return client.post(LIST_URL, data=json.dumps({"kinds": kinds}), headers=headers)


def _update(client, headers, key, kind, value, unique=None):
    """Call the update endpoint."""
    payload = {"key": key, "kind": kind, "value": value}
    if unique is not None:
        payload["unique"] = unique

    return client.put(UPDATE_URL, data=json.dumps(payload), headers=headers)


def _by_kind(items):
    """Index a listing response by kind."""
    return {item["kind"]: item for item in items}


# ---------------------------------------------------------------------------
# listing
# ---------------------------------------------------------------------------


def test_list_requires_an_admin_permission(client, analyst_headers):
    """Listing schema memory without INTEGRATION_UTILS or ADMIN_ROUTES is refused [401 UNAUTHORIZED]."""
    response = _list(client, analyst_headers, [_ALPHA_KIND])

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_is_allowed_for_admin(client, admin_headers, seed_memory):
    """ADMIN holds INTEGRATION_UTILS and may list schema memory."""
    response = _list(client, admin_headers, [_ALPHA_KIND])

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"][0]["key"] == seed_memory[_ALPHA_KIND]


def test_list_is_allowed_for_curator_through_admin_routes(client, curator_headers):
    """CURATOR lacks INTEGRATION_UTILS but ADMIN_ROUTES alone grants the listing."""
    response = _list(client, curator_headers, [_ALPHA_KIND])

    assert response.status_code == status.HTTP_200_OK


def test_list_returns_key_kind_and_value(client, admin_headers, seed_memory):
    """A listed entry carries its key, its kind and the stored json value."""
    response = _list(client, admin_headers, [_ALPHA_KIND])

    assert response.status_code == status.HTTP_200_OK
    items = response.get_json()["data"]
    assert len(items) == 1
    assert items[0] == {
        "key": seed_memory[_ALPHA_KIND],
        "kind": _ALPHA_KIND,
        "value": _ALPHA_VALUE,
    }


def test_list_returns_only_the_requested_kinds(client, admin_headers):
    """The kinds filter narrows the stored rows to the requested kinds."""
    response = _list(client, admin_headers, [_ALPHA_KIND])

    assert response.status_code == status.HTTP_200_OK
    assert _BETA_KIND not in _by_kind(response.get_json()["data"])


def test_list_returns_a_placeholder_for_a_kind_without_a_record(client, admin_headers):
    """A requested kind that has no row still comes back, with an empty value."""
    missing = f"{_PREFIX}-does-not-exist"

    response = _list(client, admin_headers, [missing])

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == [{"key": None, "kind": missing, "value": []}]


def test_list_mixes_stored_rows_and_placeholders(client, admin_headers, seed_memory):
    """Stored kinds keep their value while missing kinds are padded with placeholders."""
    missing = f"{_PREFIX}-missing"

    response = _list(client, admin_headers, [_ALPHA_KIND, missing, _BETA_KIND])

    assert response.status_code == status.HTTP_200_OK
    items = _by_kind(response.get_json()["data"])
    assert set(items) == {_ALPHA_KIND, missing, _BETA_KIND}
    assert items[_ALPHA_KIND]["value"] == _ALPHA_VALUE
    assert items[_BETA_KIND]["value"] == _BETA_VALUE
    assert items[missing] == {"key": None, "kind": missing, "value": []}


def test_list_without_kinds_returns_empty(client, admin_headers):
    """Omitting the kinds attribute lists nothing rather than everything."""
    response = client.post(LIST_URL, data=json.dumps({}), headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == []


def test_list_escapes_the_kind_of_a_placeholder(client, admin_headers):
    """A placeholder kind is html-escaped before being echoed back."""
    response = _list(client, admin_headers, [f"{_PREFIX}-<script>"])

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"][0]["kind"] == f"{_PREFIX}-&lt;script&gt;"


# ---------------------------------------------------------------------------
# listing: the map-schedules special case
# ---------------------------------------------------------------------------


@pytest.fixture
def recent_intervals():
    """Create a recent prescription carrying distinctive drug intervals.

    Returns the intervals that must show up in a derived map-schedules list.
    The prescription and its drugs use reserved test ids, so the session-wide
    clean_test_artifacts fixture removes them.
    """
    id_prescription = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1
    admission_number = test_counters["admission_number"]
    test_counters["admission_number"] += 1

    create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=1,
        date=datetime.now() - timedelta(hours=1),
    )

    id_prescription_drug = int(f"{id_prescription}001")
    intervals = ["ZZTEST 06:00", "ZZTEST 18:00"]

    for offset, interval in enumerate(intervals):
        create_prescription_drug(
            id=id_prescription_drug + offset,
            idPrescription=id_prescription,
            idDrug=3,
            interval=interval,
        )

    # a drug without an interval must not reach the derived list
    create_prescription_drug(
        id=id_prescription_drug + len(intervals),
        idPrescription=id_prescription,
        idDrug=4,
        interval=None,
    )
    # ...and neither must an empty one
    create_prescription_drug(
        id=id_prescription_drug + len(intervals) + 1,
        idPrescription=id_prescription,
        idDrug=4,
        interval="",
    )

    return intervals


def test_list_derives_map_schedules_from_recent_prescriptions(
    client, admin_headers, recent_intervals
):
    """With no stored row, map-schedules is built from recent prescription intervals."""
    response = _list(client, admin_headers, [_SCHEDULES_KIND])

    assert response.status_code == status.HTTP_200_OK
    item = response.get_json()["data"][0]
    assert item["key"] is None
    assert item["kind"] == _SCHEDULES_KIND

    derived = item["value"]
    for interval in recent_intervals:
        assert {"id": interval, "value": interval} in derived


def test_list_omits_blank_intervals_from_map_schedules(
    client, admin_headers, recent_intervals
):
    """Null and empty intervals are skipped when deriving map-schedules."""
    response = _list(client, admin_headers, [_SCHEDULES_KIND])

    assert response.status_code == status.HTTP_200_OK
    values = {entry["value"] for entry in response.get_json()["data"][0]["value"]}
    assert None not in values
    assert "" not in values


def test_list_does_not_derive_map_schedules_when_a_row_exists(
    client, admin_headers, recent_intervals
):
    """A stored map-schedules row is returned as-is, without touching prescriptions."""
    stored = [{"id": "ZZTEST stored", "value": "ZZTEST stored"}]
    key = _insert(_SCHEDULES_KIND, stored)
    session_commit()

    try:
        response = _list(client, admin_headers, [_SCHEDULES_KIND])

        assert response.status_code == status.HTTP_200_OK
        item = response.get_json()["data"][0]
        assert item["key"] == key
        assert item["value"] == stored
    finally:
        session.execute(
            text("DELETE FROM demo.memoria WHERE idmemoria = :key AND tipo = :kind"),
            {"key": key, "kind": _SCHEDULES_KIND},
        )
        session_commit()


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_requires_the_app_features_permission(
    client, analyst_headers, seed_memory
):
    """Updating schema memory without ADMIN_APP_FEATURES is refused [401 UNAUTHORIZED]."""
    key = seed_memory[_ALPHA_KIND]

    response = _update(client, analyst_headers, key, _ALPHA_KIND, {"label": "x"})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    session_commit()
    assert _rows(_ALPHA_KIND)[0][1] == _ALPHA_VALUE


def test_update_replaces_the_value(client, admin_headers, seed_memory):
    """Updating stores the new value and echoes the key back."""
    key = seed_memory[_ALPHA_KIND]
    new_value = {"label": "alpha updated", "enabled": False}

    response = _update(client, admin_headers, key, _ALPHA_KIND, new_value)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == str(key)

    session_commit()
    rows = _rows(_ALPHA_KIND)
    assert len(rows) == 1
    assert rows[0][1] == new_value


def test_update_keeps_a_backup_of_the_previous_value(
    client, admin_headers, seed_memory
):
    """The previous value is preserved in a row whose kind ends with _bkp."""
    key = seed_memory[_BETA_KIND]

    response = _update(client, admin_headers, key, _BETA_KIND, ["three"])

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    backup = _rows(f"{_BETA_KIND}_bkp")
    assert len(backup) == 1
    assert backup[0][1] == _BETA_VALUE
    # the snapshot keeps the authorship of the value it holds
    assert backup[0][2] == _SEED_USER_ID


def test_update_stamps_the_current_user(client, admin_headers, seed_memory):
    """The updated row records the user who performed the change."""
    key = seed_memory[_ALPHA_KIND]

    response = _update(client, admin_headers, key, _ALPHA_KIND, {"label": "v2"})

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    assert _rows(_ALPHA_KIND)[0][2] == _ADMIN_USER_ID


def test_update_creates_a_row_when_the_kind_has_none(client, admin_headers):
    """A kind without a record is inserted instead of updated, and leaves no backup."""
    kind = f"{_PREFIX}-created"

    response = _update(client, admin_headers, None, kind, {"label": "brand new"})

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    rows = _rows(kind)
    assert len(rows) == 1
    assert rows[0][1] == {"label": "brand new"}
    assert rows[0][2] == _ADMIN_USER_ID
    assert _rows(f"{kind}_bkp") == []


def test_update_matches_by_key_and_kind(client, admin_headers, seed_memory):
    """Without the unique flag the row is looked up by key and kind together."""
    # the beta key with the alpha kind matches nothing, so a new row appears
    response = _update(
        client, admin_headers, seed_memory[_BETA_KIND], _ALPHA_KIND, {"label": "new"}
    )

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    rows = _rows(_ALPHA_KIND)
    assert len(rows) == 2
    # the original row is untouched
    assert {row[1]["label"] for row in rows} == {"alpha", "new"}


def test_update_with_unique_ignores_the_key(client, admin_headers, seed_memory):
    """The unique flag resolves the row by kind alone, whatever key is sent."""
    response = _update(
        client,
        admin_headers,
        seed_memory[_BETA_KIND],
        _ALPHA_KIND,
        {"label": "unique"},
        unique=True,
    )

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    rows = _rows(_ALPHA_KIND)
    assert len(rows) == 1
    assert rows[0][0] == seed_memory[_ALPHA_KIND]
    assert rows[0][1] == {"label": "unique"}


# ---------------------------------------------------------------------------
# update: the protected feature flags
# ---------------------------------------------------------------------------


def test_update_features_accepts_a_protected_flag_for_admin(
    client, admin_headers, features_row
):
    """ADMIN holds INTEGRATION_UTILS and may toggle a protected feature."""
    new_value = list(features_row["value"]) + [FeatureEnum.PRIMARY_CARE.value]

    response = _update(
        client, admin_headers, features_row["key"], _FEATURES_KIND, new_value
    )

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    assert FeatureEnum.PRIMARY_CARE.value in _rows(_FEATURES_KIND)[0][1]


def test_update_features_refuses_a_protected_flag_for_curator(
    client, curator_headers, features_row
):
    """CURATOR has ADMIN_APP_FEATURES but adding OAUTH needs INTEGRATION_UTILS [403 FORBIDDEN]."""
    new_value = list(features_row["value"]) + [FeatureEnum.OAUTH.value]

    response = _update(
        client, curator_headers, features_row["key"], _FEATURES_KIND, new_value
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.get_json()["code"] == "errors.unauthorized"
    assert FeatureEnum.OAUTH.value in response.get_json()["message"]

    session_commit()
    assert _rows(_FEATURES_KIND)[0][1] == features_row["value"]


def test_update_features_refuses_removing_a_protected_flag_for_curator(
    client, curator_headers, features_row
):
    """Dropping a protected feature is guarded just like adding one [403 FORBIDDEN]."""
    protected = FeatureEnum.PATIENT_DAY_OUTPATIENT_FLOW.value
    session.execute(
        text(
            "UPDATE demo.memoria SET valor = CAST(:value AS json) "
            "WHERE idmemoria = :key AND tipo = :kind"
        ),
        {
            "value": json.dumps(list(features_row["value"]) + [protected]),
            "key": features_row["key"],
            "kind": _FEATURES_KIND,
        },
    )
    session_commit()

    response = _update(
        client,
        curator_headers,
        features_row["key"],
        _FEATURES_KIND,
        list(features_row["value"]),
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.get_json()["code"] == "errors.unauthorized"

    session_commit()
    assert protected in _rows(_FEATURES_KIND)[0][1]


def test_update_features_accepts_an_unprotected_flag_for_curator(
    client, curator_headers, features_row
):
    """A feature outside the protected set is editable with ADMIN_APP_FEATURES alone."""
    new_value = list(features_row["value"]) + [FeatureEnum.DISABLE_SOLUTION_TAB.value]

    response = _update(
        client, curator_headers, features_row["key"], _FEATURES_KIND, new_value
    )

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    stored = _rows(_FEATURES_KIND)[0]
    assert FeatureEnum.DISABLE_SOLUTION_TAB.value in stored[1]
    assert stored[2] == _CURATOR_USER_ID


def test_update_features_refusal_leaves_no_backup(
    client, curator_headers, features_row
):
    """A refused features update must not create a _bkp snapshot."""
    new_value = list(features_row["value"]) + [FeatureEnum.PRIMARY_CARE.value]

    response = _update(
        client, curator_headers, features_row["key"], _FEATURES_KIND, new_value
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN

    session_commit()
    assert _rows(f"{_FEATURES_KIND}_bkp") == []
