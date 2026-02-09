"""Application handlers.

This module contains error handlers and utility endpoints.
"""

from flask import jsonify
from flask_jwt_extended import unset_refresh_cookies

from config import Config
from utils import logger, status


def register_handlers(app):
    """Register error handlers and utility endpoints.

    Args:
        app: Flask application instance
    """

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Global exception handler for unexpected errors."""
        logger.backend_logger.exception(str(e))

        return {"status": "error", "message": "Erro inesperado"}, 500

    # JWT Error Handlers
    from .extensions import jwt

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        """Handle expired JWT tokens by clearing cookies."""
        # Check if this is a refresh token (has 'type': 'refresh' in payload)
        is_refresh_token = jwt_payload.get("type") == "refresh"

        response = jsonify(
            {"status": "error", "message": "Token expirado", "code": "TOKEN_EXPIRED"}
        )
        response.status_code = status.HTTP_401_UNAUTHORIZED

        # Clear refresh token cookies if it was a refresh token
        if is_refresh_token:
            unset_refresh_cookies(response)

        return response

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        """Handle invalid JWT tokens by clearing cookies."""
        response = jsonify(
            {"status": "error", "message": "Token inválido", "code": "INVALID_TOKEN"}
        )
        response.status_code = status.HTTP_401_UNAUTHORIZED

        # Always unset refresh cookies on invalid token
        unset_refresh_cookies(response)

        return response

    @jwt.unauthorized_loader
    def unauthorized_callback(error):
        """Handle missing JWT tokens."""
        return {
            "status": "error",
            "message": "Token ausente",
            "code": "MISSING_TOKEN",
        }, status.HTTP_401_UNAUTHORIZED

    @app.route("/version", methods=["GET"])
    def get_version():
        """Get backend version."""
        return {"status": "success", "data": Config.VERSION}, status.HTTP_200_OK
