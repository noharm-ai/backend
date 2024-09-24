import boto3
import dateutil
from datetime import timedelta
from botocore.exceptions import ClientError

from config import Config
from utils.dateutils import to_iso


def _get_client():
    return boto3.client(
        "s3",
        aws_access_key_id=Config.CACHE_BUCKET_ID,
        aws_secret_access_key=Config.CACHE_BUCKET_KEY,
    )


def get_resource_name(report, schema, filename="current"):
    return f"reports/{schema}/{report}/{filename}.gz"


def generate_link(report, schema, filename="current"):
    client = _get_client()

    cache_data = get_cache_data(report=report, schema=schema, filename=filename)

    if cache_data["exists"]:
        return client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": Config.CACHE_BUCKET_NAME,
                "Key": get_resource_name(report, schema, filename),
            },
            ExpiresIn=100,
        )

    return None


def get_cache_data(report, schema, filename="current"):
    client = _get_client()

    try:
        resource_info = client.head_object(
            Bucket=Config.CACHE_BUCKET_NAME,
            Key=get_resource_name(report=report, schema=schema, filename=filename),
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

    reports = sorted(
        file_list,
        key=lambda d: d["updateAt"] if d["updateAt"] != None else "",
        reverse=True,
    )
    # remove first
    reports.pop(0)

    return reports
