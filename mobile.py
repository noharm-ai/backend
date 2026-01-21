"""Application entrypoint.

This is the main entry point for the NoHarm backend application.
It creates the Flask application using the application factory pattern.
"""

from app import create_app
from config import Config
from models.enums import NoHarmENV

# Create the Flask application
app = create_app()

if __name__ == "__main__":
    # Configure debug mode based on environment
    app.debug = Config.ENV == NoHarmENV.DEVELOPMENT.value

    # Run the development server
    app.run(host="0.0.0.0")
