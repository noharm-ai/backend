"""Service: get integration reports"""

from datetime import timedelta

import boto3
import dateutil

from config import Config
from decorators.has_permission_decorator import Permission, has_permission

LINT_FILE = "nifilint.json.gz"


@has_permission(Permission.INTEGRATION_UTILS)
def get_nifilint():
    """Get nifilint report link."""

    """Retrieve the checklist presigned url from S3."""
    client = boto3.client("s3")

    resource_info = client.head_object(
        Bucket=Config.NIFI_BUCKET_NAME,
        Key=LINT_FILE,
    )

    resource_date = dateutil.parser.parse(
        resource_info["ResponseMetadata"]["HTTPHeaders"]["last-modified"],
    ) - timedelta(hours=3)

    presg_url = client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": Config.NIFI_BUCKET_NAME,
            "Key": LINT_FILE,
        },
        ExpiresIn=100,
    )

    return {
        "cached": True,
        "url": presg_url,
        "updatedAt": resource_date.replace(tzinfo=None).isoformat(),
    }
