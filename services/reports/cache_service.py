import boto3
import dateutil
from datetime import timedelta, datetime
from botocore.exceptions import ClientError

from config import Config


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
