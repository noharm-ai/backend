"""Unit tests for the two services that talk to S3 directly.

Everything else in the backend reaches S3 through a cache or through the
private lambda; these two go to the bucket themselves and neither had any
coverage:

* ``services.reports.reports_integration_service.get_nifilint`` — hands the
  integration team a short-lived presigned link to the nifilint archive,
  together with the archive's own timestamp read from the ``last-modified``
  header (shifted to America/Sao_Paulo and returned naive);
* ``services.storage_service.list_folders`` — folds a paginated
  ``list_objects_v2`` listing into the set of top-level folder names, taking
  them both from the delimiter's ``CommonPrefixes`` and from nested object keys.

``utils.aws`` is mocked throughout, so no AWS access happens. The
``@has_permission(INTEGRATION_UTILS)`` gate resolves the caller from the JWT
identity, so the JWT lookup and the ``User`` model are patched to inject a
fabricated user inside a Flask request context.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from exception.authorization_error import AuthorizationError
from mobile import app
from security.role import Role
from services import storage_service
from services.reports import reports_integration_service

# ADMIN carries INTEGRATION_UTILS, PRESCRIPTION_ANALYST does not
INTEGRATION_ROLES = [Role.ADMIN.value]
NO_INTEGRATION_ROLES = [Role.PRESCRIPTION_ANALYST.value]

LAST_MODIFIED = "Wed, 12 Mar 2025 18:45:00 GMT"


@contextmanager
def acting_as(roles, schema="demo"):
    """Run the block inside a request context authenticated as ``roles``."""
    fake_user = MagicMock()
    fake_user.config = {"roles": roles}
    fake_user.schema = schema

    with app.test_request_context():
        with (
            patch(
                "decorators.has_permission_decorator.get_jwt_identity", return_value=1
            ),
            patch("decorators.has_permission_decorator.User") as mock_user_cls,
        ):
            mock_user_cls.find.return_value = fake_user
            yield


@contextmanager
def s3_answering(last_modified=LAST_MODIFIED, url="https://s3.test/nifilint"):
    """Mock the S3 client used by the integration report and yield it."""
    client = MagicMock()
    client.head_object.return_value = {
        "ResponseMetadata": {"HTTPHeaders": {"last-modified": last_modified}}
    }
    client.generate_presigned_url.return_value = url

    with patch.object(reports_integration_service, "aws") as mock_aws:
        mock_aws.get_client.return_value = client
        yield client


# --- nifilint report link ----------------------------------------------------


def test_nifilint_returns_presigned_url():
    """The presigned url is returned with the archive marked as cached."""
    with acting_as(INTEGRATION_ROLES), s3_answering() as client:
        result = reports_integration_service.get_nifilint()

    assert result["cached"] is True
    assert result["url"] == "https://s3.test/nifilint"
    client.head_object.assert_called_once_with(
        Bucket=Config.NIFI_BUCKET_NAME,
        Key=reports_integration_service.LINT_FILE,
    )


def test_nifilint_presigns_the_same_object_with_a_short_expiry():
    """The link is signed for the very object that was inspected."""
    with acting_as(INTEGRATION_ROLES), s3_answering() as client:
        reports_integration_service.get_nifilint()

    client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={
            "Bucket": Config.NIFI_BUCKET_NAME,
            "Key": reports_integration_service.LINT_FILE,
        },
        ExpiresIn=100,
    )


def test_nifilint_converts_last_modified_to_local_time():
    """The GMT header is shifted by three hours and returned without a timezone."""
    with acting_as(INTEGRATION_ROLES), s3_answering():
        result = reports_integration_service.get_nifilint()

    assert result["updatedAt"] == "2025-03-12T15:45:00"


def test_nifilint_requires_integration_utils():
    """A role without INTEGRATION_UTILS cannot read the report link."""
    with acting_as(NO_INTEGRATION_ROLES), s3_answering():
        with pytest.raises(AuthorizationError):
            reports_integration_service.get_nifilint()


# --- bucket folder listing ---------------------------------------------------


def _client_with_pages(*pages):
    """Mock S3 client whose ``list_objects_v2`` paginator yields ``pages``."""
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = list(pages)

    return client


def test_list_folders_reads_common_prefixes():
    """Top-level folders come from the delimiter's CommonPrefixes."""
    client = _client_with_pages(
        {"CommonPrefixes": [{"Prefix": "reports/"}, {"Prefix": "exports/"}]}
    )

    folders = storage_service.list_folders(client, "zztest-bucket")

    assert sorted(folders) == ["exports", "reports"]
    client.get_paginator.assert_called_once_with("list_objects_v2")
    client.get_paginator.return_value.paginate.assert_called_once_with(
        Bucket="zztest-bucket", Delimiter="/"
    )


def test_list_folders_reads_nested_keys():
    """A nested object key also names the folder it sits under."""
    client = _client_with_pages(
        {
            "Contents": [
                {"Key": "reports/2025/january.csv"},
                {"Key": "exports/dump.json"},
            ]
        }
    )

    assert sorted(storage_service.list_folders(client, "zztest-bucket")) == [
        "exports",
        "reports",
    ]


def test_list_folders_ignores_keys_at_the_root():
    """An object sitting at the root of the bucket is not a folder."""
    client = _client_with_pages({"Contents": [{"Key": "readme.txt"}]})

    assert storage_service.list_folders(client, "zztest-bucket") == []


def test_list_folders_deduplicates_across_pages():
    """The same folder seen as a prefix and as a key is reported once."""
    client = _client_with_pages(
        {"CommonPrefixes": [{"Prefix": "reports/"}]},
        {"Contents": [{"Key": "reports/2025/january.csv"}]},
    )

    assert storage_service.list_folders(client, "zztest-bucket") == ["reports"]


def test_list_folders_combines_prefixes_and_keys_of_one_page():
    """A page carrying both shapes contributes every folder it names."""
    client = _client_with_pages(
        {
            "CommonPrefixes": [{"Prefix": "reports/"}],
            "Contents": [{"Key": "exports/dump.json"}],
        }
    )

    assert sorted(storage_service.list_folders(client, "zztest-bucket")) == [
        "exports",
        "reports",
    ]


def test_list_folders_on_an_empty_bucket():
    """An empty listing is not an error, it is an empty list."""
    client = _client_with_pages({})

    assert storage_service.list_folders(client, "zztest-bucket") == []
