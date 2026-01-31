"""Application handlers.

This module contains error handlers and utility endpoints.
"""

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

    @app.route("/version", methods=["GET"])
    def get_version():
        """Get backend version."""
        return {"status": "success", "data": Config.VERSION}, status.HTTP_200_OK
