from security.role import Role
from tests.conftest import get_access, make_headers


def _support_requester_headers(client):
    """Headers for a role that lacks READ_BASIC_FEATURES (used to assert 401)."""
    return make_headers(
        get_access(client, roles=[Role.SUPPORT_REQUESTER.value])
    )


def test_get_segments_success(client, analyst_headers):
    """Test get /segments - returns 200 with the seeded segments and expected fields"""
    response = client.get("/segments", headers=analyst_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert isinstance(data, list)

    segments_by_id = {s["id"]: s for s in data}

    # Seed data contains two segments (see noharm-ai/database seed)
    assert 1 in segments_by_id
    assert 2 in segments_by_id

    # Every serialized segment exposes the documented fields
    for segment in data:
        assert set(segment.keys()) == {"id", "description", "status", "type", "cpoe"}


def test_get_segments_cpoe_flag(client, analyst_headers):
    """Test get /segments - the cpoe flag reflects the underlying segment configuration"""
    response = client.get("/segments", headers=analyst_headers)
    segments_by_id = {s["id"]: s for s in response.get_json()["data"]}

    assert response.status_code == 200
    # Segment 1 is a regular segment, segment 2 is the CPOE segment
    assert segments_by_id[1]["cpoe"] is False
    assert segments_by_id[2]["cpoe"] is True


def test_get_segments_ordered_by_description(client, analyst_headers):
    """Test get /segments - results are ordered ascending by description"""
    response = client.get("/segments", headers=analyst_headers)
    descriptions = [s["description"] for s in response.get_json()["data"]]

    assert response.status_code == 200
    assert descriptions == sorted(descriptions)


def test_get_segments_requires_basic_features_permission(client):
    """Test get /segments - returns 401 when the user lacks READ_BASIC_FEATURES"""
    response = client.get("/segments", headers=_support_requester_headers(client))

    assert response.status_code == 401


def test_get_segments_requires_authentication(client):
    """Test get /segments - returns 401 when no authorization header is provided"""
    response = client.get("/segments")

    assert response.status_code == 401


def test_get_segment_departments_success(client, analyst_headers):
    """Test get /segments/departments - returns 200 with a list payload"""
    response = client.get("/segments/departments", headers=analyst_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert isinstance(data, list)

    # When departments exist, each entry exposes the documented mapping fields
    for department in data:
        assert set(department.keys()) == {"idSegment", "idDepartment", "label"}


def test_get_segment_departments_requires_basic_features_permission(client):
    """Test get /segments/departments - returns 401 when the user lacks READ_BASIC_FEATURES"""
    response = client.get(
        "/segments/departments", headers=_support_requester_headers(client)
    )

    assert response.status_code == 401
