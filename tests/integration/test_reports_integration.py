"""Integration tests for GET /reports/integration/nifilint.

The NiFi lint report is a gzip file kept in S3. The endpoint does not stream
it: it answers with a short-lived presigned link and the date the file was last
written (S3 ``last-modified``, shifted to America/Sao_Paulo).

It is an admin tool on two levels: the route is marked ``is_admin`` (refused in
production whatever the role) and the service requires INTEGRATION_UTILS, which
only the ADMIN role holds. The S3 client is patched, so no AWS call is made.
"""

from unittest.mock import MagicMock, patch

import pytest

from config import Config
from models.enums import NoHarmENV
from services.reports import reports_integration_service
from utils import status

URL = "/reports/integration/nifilint"

_PRESIGNED_LINK = "https://example.com/nifilint.json.gz?signature=test"


@pytest.fixture
def s3_client():
    """A fake S3 client: the lint file was last written at 15:30 GMT"""
    client = MagicMock()
    client.head_object.return_value = {
        "ResponseMetadata": {
            "HTTPHeaders": {"last-modified": "Tue, 10 Mar 2026 15:30:00 GMT"}
        }
    }
    client.generate_presigned_url.return_value = _PRESIGNED_LINK

    with patch(
        "services.reports.reports_integration_service.aws.get_client",
        return_value=client,
    ) as get_client:
        get_client.client = client
        yield get_client


def test_admin_gets_a_presigned_link(client, admin_headers, s3_client):
    """An admin receives the presigned link and the file date [200]"""
    response = client.get(URL, headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == {
        "cached": True,
        "url": _PRESIGNED_LINK,
        # 15:30 GMT is 12:30 in São Paulo, returned without timezone
        "updatedAt": "2026-03-10T12:30:00",
    }


def test_link_points_to_the_lint_file_and_expires_quickly(
    client, admin_headers, s3_client
):
    """The S3 calls read the lint file of the NiFi bucket, and the link is short-lived"""
    client.get(URL, headers=admin_headers)

    s3 = s3_client.client
    s3_client.assert_called_once_with("s3")
    s3.head_object.assert_called_once_with(
        Bucket=Config.NIFI_BUCKET_NAME, Key=reports_integration_service.LINT_FILE
    )
    s3.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={
            "Bucket": Config.NIFI_BUCKET_NAME,
            "Key": reports_integration_service.LINT_FILE,
        },
        ExpiresIn=100,
    )


def test_user_without_integration_utils_is_refused(client, analyst_headers, s3_client):
    """A role without INTEGRATION_UTILS is refused before reaching S3 [401]"""
    response = client.get(URL, headers=analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    s3_client.assert_not_called()


def test_curator_is_refused(client, curator_headers, s3_client):
    """CURATOR holds READ_REPORTS but not INTEGRATION_UTILS [401]"""
    response = client.get(URL, headers=curator_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    s3_client.assert_not_called()


def test_refused_in_production_even_for_an_admin(
    client, admin_headers, s3_client, monkeypatch
):
    """The route is admin-only: in production it is refused for every role [401]"""
    monkeypatch.setattr(Config, "ENV", NoHarmENV.PRODUCTION.value)

    response = client.get(URL, headers=admin_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    s3_client.assert_not_called()


def test_requires_authentication(client, s3_client):
    """No token, no link [401]"""
    response = client.get(URL)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    s3_client.assert_not_called()
