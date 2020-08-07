from os import getenv
from datetime import timedelta

class Config:
    SECRET_KEY = getenv('SECRET_KEY') or 'insert_secret_key'
    POTGRESQL_CONNECTION_STRING = "postgresql://postgres@localhost/noharm"
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=int(getenv("JWT_ACCESS_TOKEN_EXPIRES", 20)))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=int(getenv("JWT_REFRESH_TOKEN_EXPIRES", 30)))
    DDC_API_URL = None
    SELF_API_URL = "http://localhost:5000/"