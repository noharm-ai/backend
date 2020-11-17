from os import getenv
from datetime import timedelta

class Config:
    SECRET_KEY = getenv('SECRET_KEY') or 'insert_secret_key'
    POTGRESQL_CONNECTION_STRING = "postgresql://postgres@localhost/noharm"
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=int(getenv("JWT_ACCESS_TOKEN_EXPIRES", 20)))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=int(getenv("JWT_REFRESH_TOKEN_EXPIRES", 30)))
    MAIL_USERNAME = "user@gmail.com"
    MAIL_PASSWORD = "password"