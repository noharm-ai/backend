from datetime import datetime, timedelta

import boto3
import dateutil
from botocore.exceptions import ClientError

from config import Config
from exception.validation_error import ValidationError
from utils import logger, status, stringutils
from utils.dateutils import to_iso


def _get_client():
    return boto3.client("s3")


def generate_link(resource_path: str):
    """Generate a presigned URL for a resource in the cache bucket.

    Args:
        report (str): The name of the report.
        schema (str): The schema of the report.
        resource_path (str): The path to the resource in the cache bucket.

    Returns:
        str: The presigned URL for the resource.
    """
    _validate_resource_path(resource_path=resource_path)

    client = _get_client()

    cache_data = get_cache_data(resource_path=resource_path)

    if cache_data["exists"]:
        return client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": Config.CACHE_BUCKET_NAME,
                "Key": resource_path,
            },
            ExpiresIn=100,
        )

    return None


def get_cache_data(resource_path: str):
    client = _get_client()

    _validate_resource_path(resource_path=resource_path)

    try:
        resource_info = client.head_object(
            Bucket=Config.CACHE_BUCKET_NAME,
            Key=resource_path,
        )

        resource_date = dateutil.parser.parse(
            resource_info["ResponseMetadata"]["HTTPHeaders"]["last-modified"],
        ) - timedelta(hours=3)

        return {
            "exists": True,
            "updatedAt": resource_date.replace(tzinfo=None).isoformat(),
        }
    except ClientError:
        return {"exists": False, "updatedAt": None}


def list_available_reports(schema: str, report: str):
    """List of available reports for a given schema and report type.

    Args:
        schema (str): The schema name.
        report (str): The report type.

    Returns:
        list: A list of available reports.
    """

    _validate_resource_path(resource_path=report)

    client = _get_client()
    files = client.list_objects_v2(
        Bucket=Config.CACHE_BUCKET_NAME,
        Prefix=f"reports/{schema}/{report}/",
    )

    file_list = []
    for f in files["Contents"]:
        filename = f["Key"].split("/")[-1].replace(".gz", "")
        if filename != "current":
            file_list.append(
                {
                    "name": f["Key"].split("/")[-1].replace(".gz", ""),
                    "updateAt": to_iso(f["LastModified"]),
                }
            )

    if len(file_list) > 0:
        reports = sorted(
            file_list,
            key=lambda d: d["name"] if d["name"] != None else "",
            reverse=True,
        )
        # remove first
        reports.pop(0)

        return reports

    return []


def list_available_custom_reports(schema: str, id_report: int):
    """List of available custom reports for a given schema and report type.

    Args:
        schema (str): The schema name.
        id_report (int): The report id.

    Returns:
        list: A list of available reports.
    """

    resource_path = f"reports/{schema}/CUSTOM/{id_report}/"

    _validate_resource_path(resource_path=resource_path)

    client = _get_client()
    files = client.list_objects_v2(
        Bucket=Config.CACHE_BUCKET_NAME,
        Prefix=resource_path,
    )

    current_report = (
        {
            "name": datetime.now().strftime("%Y-%m-%d"),
            "filename": None,
            "updateAt": None,
            "ready": False,
        },
    )

    if "Contents" not in files:
        return [current_report]

    file_list = []
    for f in files["Contents"]:
        if "csv" not in f["Key"]:
            continue

        filename = (
            f["Key"]
            .split("/")[-1]
            .replace(".gz", "")
            .replace("csv_", "")
            .replace(".csv", "")
        )

        file_list.append(
            {
                "name": filename,
                "filename": f["Key"].split("/")[-1],
                "updateAt": to_iso(f["LastModified"]),
                "ready": True,
            }
        )

    if not file_list:
        return []

    reports = sorted(
        file_list,
        key=lambda d: d["name"] if d["name"] is not None else "",
        reverse=True,
    )

    if reports[0]["name"] != datetime.now().strftime("%Y-%m-%d"):
        reports.insert(0, current_report)

    return reports


def _validate_resource_path(resource_path: str):
    if not stringutils.is_valid_filename(resource_path=resource_path):
        logger.backend_logger.warning("invalid filename: %s", resource_path)
        raise ValidationError(
            "Nome de arquivo inválido",
            "errors.invalidFilename",
            status.HTTP_400_BAD_REQUEST,
        )
