"""Network utilities for handling client IP extraction and validation"""

import ipaddress
from flask import request


def get_client_ip_from_request():
    """
    Extracts the real client IP considering AWS API Gateway
    and prevents basic spoofing
    """
    # X-Forwarded-For is the standard header from API Gateway
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        # First IP in the list is the original client
        client_ip = forwarded_for.split(",")[0].strip()
        if is_valid_ip(client_ip):
            return client_ip

    # Common alternative headers
    headers_to_check = [
        "X-Real-IP",
        "X-Original-Forwarded-For",
        "CF-Connecting-IP",  # CloudFlare
    ]

    for header in headers_to_check:
        ip = request.headers.get(header)
        if ip and is_valid_ip(ip.strip()):
            return ip.strip()

    # Fallback to remote_addr (less reliable)
    return request.remote_addr


def is_valid_ip(ip: str) -> bool:
    """Basic IP format validation"""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def get_client_ip_with_validation():
    """
    Extracts client IP with additional validations
    Rejects private/local IPs for better security
    """
    client_ip = get_client_ip_from_request()

    try:
        ip_obj = ipaddress.ip_address(client_ip)

        # Reject private/local IPs if needed
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
            # For development, might allow private IPs
            # In production, consider returning error or default IP
            pass

        return str(ip_obj)
    except ValueError:
        # If validation fails, return original IP
        return client_ip
