"""Application handlers.

This module contains error handlers and utility endpoints.
"""

from flask import jsonify, request
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

    @app.before_request
    def debug_refresh_token():
        if request.path == "/refresh-token" and request.method == "POST":
            refresh_cookie = request.cookies.get("refresh_token_cookie")
            logger.backend_logger.warning("DEBUG COOKIE: %s", str(refresh_cookie))

    # JWT Error Handlers
    from .extensions import jwt

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        """Handle invalid JWT tokens by clearing cookies."""
        response = jsonify(
            {"status": "error", "message": "Token inválido", "code": "INVALID_TOKEN"}
        )
        response.status_code = status.HTTP_401_UNAUTHORIZED

        logger.backend_logger.warning("UNSET REFRESH COOKIES: %s", str(error))

        # Always unset refresh cookies on invalid token
        unset_refresh_cookies(response)

        return response

    @app.route("/version", methods=["GET"])
    def get_version():
        """Get backend version."""
        return {"status": "success", "data": Config.VERSION}, status.HTTP_200_OK
