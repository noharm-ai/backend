"""Cached boto3 client/resource factories.

Creating a boto3 client or resource is expensive: it resolves credentials and
sets up the endpoint/TLS configuration. Doing that on every request adds
latency and, on AWS Lambda, throws away work a warm container could reuse
across invocations.

These helpers cache one instance per ``(service_name, region_name)`` pair so
callers share a single long-lived client/resource. boto3 clients are
thread-safe for API calls, so sharing them is safe.
"""

from functools import lru_cache

import boto3


@lru_cache(maxsize=None)
def get_client(service_name: str, region_name: str = None):
    """Return a cached boto3 client for the given service and region."""
    return boto3.client(service_name, region_name=region_name)


@lru_cache(maxsize=None)
def get_resource(service_name: str, region_name: str = None):
    """Return a cached boto3 resource for the given service and region."""
    return boto3.resource(service_name, region_name=region_name)
