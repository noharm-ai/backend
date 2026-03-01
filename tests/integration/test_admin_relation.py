from utils import status


def test_relation_list_allow_admin(client, admin_headers):
    response = client.post(
        "/admin/relation/list",
        json={"limit": 1, "offset": 0},
        headers=admin_headers,
    )

    assert response.status_code == status.HTTP_200_OK


def test_relation_list_deny_analyst(client, analyst_headers):
    response = client.post(
        "/admin/relation/list",
        json={"limit": 1, "offset": 0},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
