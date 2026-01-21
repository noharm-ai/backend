"""Application factory.

This module contains the Flask application factory that creates
and configures the Flask application instance.
"""

import os

from flask import Flask

from .blueprints import register_blueprints
from .extensions import cors, db, jwt, mail
from .flask_config import get_config
from .handlers import register_handlers
from .logging_config import configure_logging
from .security import configure_security_headers

# Set timezone
os.environ["TZ"] = "America/Sao_Paulo"


def create_app(config_name=None):
    """Application factory for creating Flask app instances.

    Args:
        config_name: Optional config name ('development', 'production', 'test').
                    If None, uses environment from Config.ENV.

    Returns:
        Configured Flask application instance
    """
    # Create Flask app
    app = Flask(__name__)

    # Load configuration
    config_class = get_config(config_name)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    jwt.init_app(app)
    mail.init_app(app)
    cors.init_app(
        app,
        origins=app.config["CORS_ORIGINS"],
        supports_credentials=app.config["CORS_SUPPORTS_CREDENTIALS"],
    )

    # Configure logging
    configure_logging()

    # Register blueprints
    register_blueprints(app)

    # Register handlers (error handlers and utility endpoints)
    register_handlers(app)

    # Configure security headers
    configure_security_headers(app)

    return app
