"""Flask extensions initialization.

This module creates extension instances that will be initialized
with the Flask app in the application factory.
"""

from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_mail import Mail
from flask_sqlalchemy import SQLAlchemy

# Create extension instances without app binding
# These will be initialized in the application factory via init_app()
db = SQLAlchemy()
jwt = JWTManager()
mail = Mail()
cors = CORS()
