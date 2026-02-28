from security.role import Role
from tests.conftest import get_access, make_headers
from utils import status


def test_relation_list_allow_admin(client):
    headers = make_headers(get_access(client, roles=[Role.ADMIN.value]))

    response = client.post(
        "/admin/relation/list",
        json={"limit": 1, "offset": 0},
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK


def test_relation_list_deny_curator(client):
    headers = make_headers(get_access(client, roles=[Role.CURATOR.value]))

    response = client.post(
        "/admin/relation/list",
        json={"limit": 1, "offset": 0},
        headers=headers,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
