"""Tests: services/reports/reports_cache_service.py

The S3 report cache. Every entry point validates the resource path before it
touches S3, so the traversal guard is exercised alongside the listing and
presigned-link behaviour.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from exception.validation_error import ValidationError
from services.reports import reports_cache_service
from utils import status

BUCKET = "test-cache-bucket"

# Paths rejected by utils.stringutils.is_valid_filename
INVALID_PATHS = [
    "reports/demo/../../etc/passwd",  # plain traversal
    "reports%2fdemo%2fx",  # url-encoded separator
    "reports/%2e%2e/demo",  # url-encoded traversal
    "reports\\demo\\x",  # backslash separator
    "reports/demo/x\x00.csv",  # null byte
    "reports/demo/x y.csv",  # space (outside the allowed charset)
    "",  # empty
]


@pytest.fixture
def s3_mock():
    """Replace the boto3 client used by the service and pin the bucket name"""
    client = MagicMock()
    with (
        patch.object(reports_cache_service, "_get_client", return_value=client),
        patch.object(reports_cache_service.Config, "CACHE_BUCKET_NAME", BUCKET),
    ):
        yield client


def _head_object_response(last_modified: str):
    """Shape of the head_object payload the service reads the timestamp from"""
    return {"ResponseMetadata": {"HTTPHeaders": {"last-modified": last_modified}}}


def _client_error():
    return ClientError({"Error": {"Code": "404"}}, "HeadObject")


# ---------------------------------------------------------------------------
# resource path validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("resource_path", INVALID_PATHS)
def test_generate_link_rejects_invalid_path(s3_mock, resource_path):
    """generate_link refuses a path that fails the filename guard"""
    with pytest.raises(ValidationError) as exc:
        reports_cache_service.generate_link(resource_path=resource_path)

    assert exc.value.code == "errors.invalidFilename"
    assert exc.value.httpStatus == status.HTTP_400_BAD_REQUEST
    s3_mock.generate_presigned_url.assert_not_called()
    s3_mock.head_object.assert_not_called()


@pytest.mark.parametrize("resource_path", INVALID_PATHS)
def test_get_cache_data_rejects_invalid_path(s3_mock, resource_path):
    """get_cache_data refuses a path that fails the filename guard"""
    with pytest.raises(ValidationError) as exc:
        reports_cache_service.get_cache_data(resource_path=resource_path)

    assert exc.value.code == "errors.invalidFilename"
    s3_mock.head_object.assert_not_called()


@pytest.mark.parametrize("report", INVALID_PATHS)
def test_list_available_reports_rejects_invalid_report(s3_mock, report):
    """list_available_reports refuses a report name that fails the filename guard"""
    with pytest.raises(ValidationError) as exc:
        reports_cache_service.list_available_reports(schema="demo", report=report)

    assert exc.value.code == "errors.invalidFilename"
    s3_mock.list_objects_v2.assert_not_called()


# ---------------------------------------------------------------------------
# get_cache_data
# ---------------------------------------------------------------------------


def test_get_cache_data_returns_timestamp_shifted_to_local_time(s3_mock):
    """The S3 last-modified header (UTC) is reported 3 hours back, without a tzinfo"""
    s3_mock.head_object.return_value = _head_object_response(
        "Wed, 15 May 2024 12:30:00 GMT"
    )

    result = reports_cache_service.get_cache_data(
        resource_path="reports/demo/GENERAL/current.gz"
    )

    assert result == {"exists": True, "updatedAt": "2024-05-15T09:30:00"}
    s3_mock.head_object.assert_called_once_with(
        Bucket=BUCKET, Key="reports/demo/GENERAL/current.gz"
    )


def test_get_cache_data_reports_missing_object(s3_mock):
    """A ClientError from head_object means the cached report is not there yet"""
    s3_mock.head_object.side_effect = _client_error()

    result = reports_cache_service.get_cache_data(
        resource_path="reports/demo/GENERAL/current.gz"
    )

    assert result == {"exists": False, "updatedAt": None}


# ---------------------------------------------------------------------------
# generate_link
# ---------------------------------------------------------------------------


def test_generate_link_returns_presigned_url_when_object_exists(s3_mock):
    """An existing object yields a short-lived presigned GET url"""
    s3_mock.head_object.return_value = _head_object_response(
        "Wed, 15 May 2024 12:30:00 GMT"
    )
    s3_mock.generate_presigned_url.return_value = "https://s3.example/signed"

    link = reports_cache_service.generate_link(
        resource_path="reports/demo/GENERAL/current.gz"
    )

    assert link == "https://s3.example/signed"
    s3_mock.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": BUCKET, "Key": "reports/demo/GENERAL/current.gz"},
        ExpiresIn=100,
    )


def test_generate_link_returns_none_when_object_is_missing(s3_mock):
    """No cached object means no link — and no signing call"""
    s3_mock.head_object.side_effect = _client_error()

    link = reports_cache_service.generate_link(
        resource_path="reports/demo/GENERAL/current.gz"
    )

    assert link is None
    s3_mock.generate_presigned_url.assert_not_called()


# ---------------------------------------------------------------------------
# list_available_reports
# ---------------------------------------------------------------------------


def _s3_object(key: str, last_modified: datetime = datetime(2024, 5, 15, 10, 0, 0)):
    return {"Key": key, "LastModified": last_modified}


def test_list_available_reports_drops_current_parquet_and_newest(s3_mock):
    """Only dated .gz snapshots are listed, newest first, minus the most recent one.

    The newest snapshot is dropped because it is already served as `current`.
    """
    s3_mock.list_objects_v2.return_value = {
        "Contents": [
            _s3_object("reports/demo/GENERAL/2024-05-01.gz"),
            _s3_object("reports/demo/GENERAL/2024-05-03.gz"),
            _s3_object("reports/demo/GENERAL/2024-05-02.gz"),
            _s3_object("reports/demo/GENERAL/current.gz"),
            _s3_object("reports/demo/GENERAL/2024-05-04.parquet"),
        ]
    }

    reports = reports_cache_service.list_available_reports(
        schema="demo", report="GENERAL"
    )

    assert [r["name"] for r in reports] == ["2024-05-02", "2024-05-01"]
    s3_mock.list_objects_v2.assert_called_once_with(
        Bucket=BUCKET, Prefix="reports/demo/GENERAL/"
    )


def test_list_available_reports_exposes_last_modified_as_iso(s3_mock):
    """Each entry carries the S3 LastModified timestamp in ISO format"""
    s3_mock.list_objects_v2.return_value = {
        "Contents": [
            _s3_object("reports/demo/GENERAL/2024-05-02.gz"),
            _s3_object(
                "reports/demo/GENERAL/2024-05-01.gz", datetime(2024, 5, 1, 7, 15, 0)
            ),
        ]
    }

    reports = reports_cache_service.list_available_reports(
        schema="demo", report="GENERAL"
    )

    assert reports == [{"name": "2024-05-01", "updateAt": "2024-05-01T07:15:00"}]


def test_list_available_reports_returns_empty_when_only_current_exists(s3_mock):
    """A bucket holding just `current` has no historical snapshots to offer"""
    s3_mock.list_objects_v2.return_value = {
        "Contents": [_s3_object("reports/demo/GENERAL/current.gz")]
    }

    assert (
        reports_cache_service.list_available_reports(schema="demo", report="GENERAL")
        == []
    )


def test_list_available_reports_returns_empty_for_single_snapshot(s3_mock):
    """A lone snapshot is the current one, so nothing is left to list"""
    s3_mock.list_objects_v2.return_value = {
        "Contents": [_s3_object("reports/demo/GENERAL/2024-05-01.gz")]
    }

    assert (
        reports_cache_service.list_available_reports(schema="demo", report="GENERAL")
        == []
    )


# ---------------------------------------------------------------------------
# list_available_custom_reports
# ---------------------------------------------------------------------------


# The service builds this placeholder for the not-yet-generated report of the
# current day. NOTE: it is wrapped in a 1-tuple by a trailing comma in
# reports_cache_service.list_available_custom_reports, so it reaches the caller
# as a tuple rather than a dict. The assertions below pin the shape that
# currently ships; the tuple looks unintended given the sibling entries are
# plain dicts.
def _pending_today():
    return (
        {
            "name": datetime.now().strftime("%Y-%m-%d"),
            "filename": None,
            "updateAt": None,
            "ready": False,
        },
    )


def test_list_available_custom_reports_without_contents_returns_pending_today(s3_mock):
    """An empty prefix still advertises today's report as pending"""
    s3_mock.list_objects_v2.return_value = {}

    reports = reports_cache_service.list_available_custom_reports(
        schema="demo", id_report=7
    )

    assert reports == [_pending_today()]
    s3_mock.list_objects_v2.assert_called_once_with(
        Bucket=BUCKET, Prefix="reports/demo/CUSTOM/7/"
    )


def test_list_available_custom_reports_ignores_non_csv_entries(s3_mock):
    """Entries that are not csv exports are not reports the user can download"""
    s3_mock.list_objects_v2.return_value = {
        "Contents": [
            _s3_object("reports/demo/CUSTOM/7/data.parquet"),
            _s3_object("reports/demo/CUSTOM/7/meta.json"),
        ]
    }

    assert (
        reports_cache_service.list_available_custom_reports(schema="demo", id_report=7)
        == []
    )


def test_list_available_custom_reports_strips_prefix_and_extension(s3_mock):
    """The display name drops the csv_ prefix and the .csv/.gz extensions"""
    s3_mock.list_objects_v2.return_value = {
        "Contents": [
            _s3_object(
                "reports/demo/CUSTOM/7/csv_2024-05-01.csv.gz",
                datetime(2024, 5, 1, 7, 15, 0),
            )
        ]
    }

    reports = reports_cache_service.list_available_custom_reports(
        schema="demo", id_report=7
    )

    # today's pending placeholder is prepended because the newest file is older
    assert reports[0] == _pending_today()
    assert reports[1] == {
        "name": "2024-05-01",
        "filename": "csv_2024-05-01.csv.gz",
        "updateAt": "2024-05-01T07:15:00",
        "ready": True,
    }


def test_list_available_custom_reports_sorts_newest_first(s3_mock):
    """Generated reports are listed newest first"""
    s3_mock.list_objects_v2.return_value = {
        "Contents": [
            _s3_object("reports/demo/CUSTOM/7/csv_2024-05-01.csv"),
            _s3_object("reports/demo/CUSTOM/7/csv_2024-05-03.csv"),
            _s3_object("reports/demo/CUSTOM/7/csv_2024-05-02.csv"),
        ]
    }

    reports = reports_cache_service.list_available_custom_reports(
        schema="demo", id_report=7
    )

    assert [r["name"] for r in reports[1:]] == [
        "2024-05-03",
        "2024-05-02",
        "2024-05-01",
    ]


def test_list_available_custom_reports_skips_placeholder_when_today_is_ready(s3_mock):
    """No pending placeholder once today's report has been generated"""
    today = datetime.now().strftime("%Y-%m-%d")
    s3_mock.list_objects_v2.return_value = {
        "Contents": [_s3_object(f"reports/demo/CUSTOM/7/csv_{today}.csv")]
    }

    reports = reports_cache_service.list_available_custom_reports(
        schema="demo", id_report=7
    )

    assert len(reports) == 1
    assert reports[0]["name"] == today
    assert reports[0]["ready"] is True
