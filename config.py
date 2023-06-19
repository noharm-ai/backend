from os import getenv
from datetime import timedelta

from models.enums import NoHarmENV


class Config:
    ENV = getenv("ENV") or NoHarmENV.PRODUCTION
    SECRET_KEY = getenv("SECRET_KEY") or ""
    API_KEY = getenv("API_KEY") or ""
    SELF_API_URL = getenv("SELF_API_URL") or ""
    APP_URL = getenv("APP_URL")
    POTGRESQL_CONNECTION_STRING = (
        getenv("POTGRESQL_CONNECTION_STRING")
        or "postgresql://postgres@localhost/noharm"
    )
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(getenv("JWT_ACCESS_TOKEN_EXPIRES", 20))
    )
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        days=int(getenv("JWT_REFRESH_TOKEN_EXPIRES", 30))
    )
    MAIL_USERNAME = getenv("MAIL_USERNAME") or "user@gmail.com"
    MAIL_PASSWORD = getenv("MAIL_PASSWORD") or "password"
    MAIL_SENDER = getenv("MAIL_SENDER") or "user@gmail.com"
    MAIL_HOST = getenv("MAIL_HOST") or "localhost"
