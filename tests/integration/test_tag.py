"""Integration tests for the /tag/list endpoint (tag_service.list_tags)."""

import pytest
from sqlalchemy import text

from tests.conftest import get_access, make_headers, session, session_commit

from models.enums import TagTypeEnum
from security.role import Role

PATIENT = TagTypeEnum.PATIENT.value  # 1
PATIENT_NAV = TagTypeEnum.PATIENT_NAVIGATION.value  # 2

TAG_ACTIVE = "zztest_tag_active"
TAG_INACTIVE = "zztest_tag_inactive"
TAG_NAV = "zztest_tag_nav"


@pytest.fixture
def seed_tags():
    """Insert distinctive marcador rows and remove them after the test."""
    rows = [
        (TAG_ACTIVE, PATIENT, True),
        (TAG_INACTIVE, PATIENT, False),
        (TAG_NAV, PATIENT_NAV, True),
    ]
    for name, tp, active in rows:
        session.execute(
            text(
                "INSERT INTO demo.marcador "
                "(nome, tp_marcador, ativo, created_at, created_by) "
                "VALUES (:nome, :tp, :ativo, now(), 1)"
            ),
            {"nome": name, "tp": tp, "ativo": active},
        )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM demo.marcador WHERE nome IN (:a, :b, :c)"),
        {"a": TAG_ACTIVE, "b": TAG_INACTIVE, "c": TAG_NAV},
    )
    session_commit()


def _names(response):
    """Extract the set of tag names from a successful response envelope."""
    return {item["name"] for item in response.get_json()["data"]}


def test_list_tags_permission_denied(client):
    """A user without READ_BASIC_FEATURES cannot list tags [401 UNAUTHORIZED]."""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))
    response = client.get("/tag/list", headers=headers)

    assert response.status_code == 401


def test_list_tags_returns_expected_shape(client, analyst_headers, seed_tags):
    """A successful listing returns objects with name, tagType and active fields."""
    response = client.get(f"/tag/list?tagType={PATIENT}", headers=analyst_headers)

    assert response.status_code == 200
    items = response.get_json()["data"]
    match = next(item for item in items if item["name"] == TAG_ACTIVE)
    assert match["tagType"] == PATIENT
    assert match["active"] is True


def test_list_patient_tags_excludes_navigation_for_analyst(
    client, analyst_headers, seed_tags
):
    """Without READ_NAV, listing patient tags excludes navigation-only tags."""
    response = client.get(f"/tag/list?tagType={PATIENT}", headers=analyst_headers)

    assert response.status_code == 200
    names = _names(response)
    assert TAG_ACTIVE in names
    assert TAG_INACTIVE in names
    assert TAG_NAV not in names


def test_list_patient_tags_active_filter(client, analyst_headers, seed_tags):
    """The active filter narrows results to active tags only."""
    response = client.get(
        f"/tag/list?tagType={PATIENT}&active=true", headers=analyst_headers
    )

    assert response.status_code == 200
    names = _names(response)
    assert TAG_ACTIVE in names
    assert TAG_INACTIVE not in names


def test_list_patient_tags_includes_navigation_for_curator(
    client, curator_headers, seed_tags
):
    """With READ_NAV, listing patient tags also includes navigation tags."""
    response = client.get(f"/tag/list?tagType={PATIENT}", headers=curator_headers)

    assert response.status_code == 200
    names = _names(response)
    assert TAG_ACTIVE in names
    assert TAG_NAV in names
