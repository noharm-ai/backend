"""Integration tests for the /segments endpoints (segment_service).

The seed database ships two segments (a non-CPOE and a CPOE one) and three
segment/department associations. These tests drive the two read endpoints
through the HTTP layer, asserting ordering, the department join shape and the
READ_BASIC_FEATURES permission gate.
"""

from tests.conftest import get_access, make_headers

from security.role import Role

# Seed identifiers (see database/noharm-insert.sql loaded into the demo schema).
SEGMENT_ADULT = 1
SEGMENT_ADULT_CPOE = 2


def _data(response):
    """Return the ``data`` payload of a successful response envelope."""
    return response.get_json()["data"]


def test_get_segments_requires_permission(client):
    """A role without READ_BASIC_FEATURES cannot list segments [401]."""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))
    response = client.get("/segments", headers=headers)

    assert response.status_code == 401


def test_get_segments_returns_seeded_rows(client, analyst_headers):
    """Listing returns the seeded segments with their id, description and cpoe flag."""
    response = client.get("/segments", headers=analyst_headers)

    assert response.status_code == 200
    by_id = {s["id"]: s for s in _data(response)}

    assert SEGMENT_ADULT in by_id
    assert SEGMENT_ADULT_CPOE in by_id
    assert by_id[SEGMENT_ADULT]["cpoe"] is False
    assert by_id[SEGMENT_ADULT_CPOE]["cpoe"] is True


def test_get_segments_ordered_by_description(client, analyst_headers):
    """Segments are returned ordered by description ascending."""
    response = client.get("/segments", headers=analyst_headers)

    descriptions = [s["description"] for s in _data(response)]
    assert descriptions == sorted(descriptions)


def test_get_segment_departments_requires_permission(client):
    """A role without READ_BASIC_FEATURES cannot list segment departments [401]."""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))
    response = client.get("/segments/departments", headers=headers)

    assert response.status_code == 401


def test_get_segment_departments_shape_and_join(client, analyst_headers):
    """Each department entry exposes idSegment, idDepartment and a label from the join."""
    response = client.get("/segments/departments", headers=analyst_headers)

    assert response.status_code == 200
    items = _data(response)
    assert len(items) >= 1

    for item in items:
        assert set(item.keys()) == {"idSegment", "idDepartment", "label"}
        assert item["label"]  # department name resolved through the join

    # the seed associates departments with both segments
    segments = {item["idSegment"] for item in items}
    assert SEGMENT_ADULT in segments
    assert SEGMENT_ADULT_CPOE in segments


def test_get_segment_departments_ordered_by_label(client, analyst_headers):
    """Segment departments are ordered by department name ascending."""
    response = client.get("/segments/departments", headers=analyst_headers)

    labels = [item["label"] for item in _data(response)]
    assert labels == sorted(labels)
