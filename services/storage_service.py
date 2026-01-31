"""Service: storage service"""


def list_folders(s3_client, bucket_name):
    """
    List all folders (prefixes) in the S3 bucket

    Args:
        s3_client: boto3 S3 client
        bucket_name (str): Name of the bucket

    Returns:
        list: List of folder names
    """
    folders = set()
    paginator = s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket_name, Delimiter="/"):
        # Get folders from CommonPrefixes
        if "CommonPrefixes" in page:
            for prefix in page["CommonPrefixes"]:
                folder_name = prefix["Prefix"].rstrip("/")
                folders.add(folder_name)

        # Also check for nested folders in Contents
        if "Contents" in page:
            for obj in page["Contents"]:
                key_parts = obj["Key"].split("/")
                if len(key_parts) > 1:
                    folder_name = key_parts[0]
                    folders.add(folder_name)

    return list(folders)
