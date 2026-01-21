"""Security configuration.

This module configures security headers for HTTP responses.
"""

# Security headers to be added to all responses
SECURITY_HEADERS = {
    "strict-transport-security": ["max-age=63072000", "includeSubDomains"],
    "content-security-policy": ["default-src 'none'", "frame-ancestors 'none'"],
    "x-frame-options": ["SAMEORIGIN"],
    "x-xss-protection": ["1", "mode=block"],
    "x-content-type-options": ["nosniff"],
    "referrer-policy": ["same-origin"],
}


def configure_security_headers(app):
    """Configure security headers for the application.

    Registers an after_request handler that adds security headers
    to all HTTP responses.

    Args:
        app: Flask application instance
    """

    @app.after_request
    def add_security_headers(response):
        for key, content in SECURITY_HEADERS.items():
            response.headers[key] = ";".join(content)
        return response
