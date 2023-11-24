import boto3
import json
import io
import gzip

from config import Config


def _get_client():
    return boto3.client(
        "s3",
        aws_access_key_id=Config.CACHE_BUCKET_ID,
        aws_secret_access_key=Config.CACHE_BUCKET_KEY,
    )


def get_resource_name(cache_id, report, schema):
    return f"{schema}_{cache_id}_{report}.gz"


def generate_link(cache_id, report, schema):
    client = _get_client()

    return client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": Config.CACHE_BUCKET_NAME,
            "Key": get_resource_name(cache_id, report, schema),
        },
        ExpiresIn=100,
    )


def save_cache(cache_id, report, schema, data):
    client = _get_client()

    file = io.BytesIO()
    with gzip.GzipFile(fileobj=file, mode="wb") as fh:
        with io.TextIOWrapper(fh, encoding="utf-8") as wrapper:
            wrapper.write(json.dumps(data, ensure_ascii=False))
    file.seek(0)

    client.put_object(
        Body=file,
        Bucket=Config.CACHE_BUCKET_NAME,
        Key=get_resource_name(cache_id, report, schema),
    )
