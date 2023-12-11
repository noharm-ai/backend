import boto3
import json
import io
import gzip
import dateutil
from dateutil.tz import tzoffset
from botocore.exceptions import ClientError
from datetime import datetime, timedelta

from config import Config


def _get_client():
    return boto3.client(
        "s3",
        aws_access_key_id=Config.CACHE_BUCKET_ID,
        aws_secret_access_key=Config.CACHE_BUCKET_KEY,
    )


def get_resource_name(report, schema):
    return f"reports/{schema}/{report}.gz"


def generate_link(report, schema):
    client = _get_client()

    return client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": Config.CACHE_BUCKET_NAME,
            "Key": get_resource_name(report, schema),
        },
        ExpiresIn=100,
    )


def save_cache(report, schema, data):
    client = _get_client()

    file = io.BytesIO()
    with gzip.GzipFile(fileobj=file, mode="wb") as fh:
        with io.TextIOWrapper(fh, encoding="utf-8") as wrapper:
            wrapper.write(json.dumps(data, ensure_ascii=False))
    file.seek(0)

    client.put_object(
        Body=file,
        Bucket=Config.CACHE_BUCKET_NAME,
        Key=get_resource_name(report, schema),
    )


def get_cache_data(report, schema):
    client = _get_client()

    try:
        resource_info = client.head_object(
            Bucket=Config.CACHE_BUCKET_NAME,
            Key=get_resource_name(report=report, schema=schema),
        )

        resource_date = dateutil.parser.parse(
            resource_info["ResponseMetadata"]["HTTPHeaders"]["last-modified"],
        ) - timedelta(hours=3)

        return {
            "isCached": datetime.today().date() == resource_date.date(),
            "updatedAt": resource_date.replace(tzinfo=None).isoformat(),
        }
    except ClientError:
        return {"isCached": False, "updatedAt": None}


def generate_link_from_cache(report, schema):
    cache_data = get_cache_data(report=report, schema=schema)

    if cache_data["isCached"]:
        return {
            "url": generate_link(report, schema),
            "updatedAt": cache_data["updatedAt"],
        }

    return None
