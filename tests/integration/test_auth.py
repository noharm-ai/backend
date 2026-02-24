import pytest
import json

from utils import status


@pytest.mark.parametrize(
    "email, password, status_code, maintainer, valid_schemas",
    [
        ("demo", "demo", status.HTTP_200_OK, False, []),
        ("demo", "1234", status.HTTP_400_BAD_REQUEST, False, []),
        ("user@admin.com", "useradmin", status.HTTP_200_OK, True, ["demo", "teste"]),
        (
            "organizationmanager",
            "organizationmanager",
            status.HTTP_200_OK,
            False,
            ["demo", "teste"],
        ),
    ],
)
def test_pre_auth(client, email, password, status_code, maintainer, valid_schemas):
    """Test pre_auth"""
    payload = {"email": email, "password": password}
    response = client.post("/pre-auth", json=payload)

    assert response.status_code == status_code

    if response.status_code == status.HTTP_200_OK:
        result = json.loads(response.data)

        assert result["maintainer"] == maintainer
        user_schemas = [schema["name"] for schema in result["schemas"]]
        assert user_schemas == valid_schemas


@pytest.mark.parametrize(
    "email, password, status_code, force_schema",
    [
        ("demo", "demo", status.HTTP_200_OK, None),
        ("demo", "demo", status.HTTP_401_UNAUTHORIZED, "demo"),
        ("demo", "demo", status.HTTP_401_UNAUTHORIZED, "teste"),
        ("demo", "1234", status.HTTP_400_BAD_REQUEST, None),
        ("user@admin.com", "useradmin", status.HTTP_401_UNAUTHORIZED, "demo"),
        ("user@admin.com", "useradmin", status.HTTP_401_UNAUTHORIZED, "teste"),
        (
            "user@admin.com",
            "useradmin",
            status.HTTP_401_UNAUTHORIZED,
            "teste2",
        ),
        ("organizationmanager", "organizationmanager", status.HTTP_200_OK, "teste"),
        (
            "organizationmanager",
            "organizationmanager",
            status.HTTP_401_UNAUTHORIZED,
            "teste2",
        ),
        # TODO: add after special roles test
        # (
        #     "invaliduser",
        #     "invaliduser",
        #     status.HTTP_500_INTERNAL_SERVER_ERROR,
        #     None,
        # ),
        (
            "invaliduser2",
            "invaliduser2",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            None,
        ),
    ],
)
def test_authenticate(client, email, password, status_code, force_schema):
    """Test authenticate"""
    payload = {"email": email, "password": password, "schema": force_schema}
    response = client.post("/authenticate", json=payload)

    assert response.status_code == status_code

    if response.status_code == status.HTTP_200_OK:
        result = json.loads(response.data)

        assert result["schema"] == (force_schema if force_schema else "demo")
