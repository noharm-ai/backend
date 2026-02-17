from flask import (
    Blueprint,
    after_this_request,
    request,
)
from flask_jwt_extended import (
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_refresh_cookies,
)

from decorators.api_endpoint_decorator import api_endpoint
from exception.validation_error import ValidationError
from models.main import db, dbSession
from services import auth_service
from utils import sessionutils, status

app_auth = Blueprint("app_auth", __name__)


# deprecated
@app_auth.route("/pre-auth", methods=["POST"])
def pre_auth():
    data = request.get_json()

    email = data.get("email", None)
    password = data.get("password", None)

    try:
        auth_data = auth_service.pre_auth(email, password)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return auth_data, status.HTTP_200_OK


@app_auth.route("/switch-schema", methods=["GET"])
@api_endpoint()
def get_switch_schema_data():
    """get schema data"""

    return auth_service.get_switch_schema_data()


@app_auth.route("/switch-schema", methods=["POST"])
@api_endpoint()
def switch_schema():
    """switch between schemas"""
    data = request.get_json()

    schema = data.get("schema", None)
    extra_features = data.get("extraFeatures", None)

    auth_data = auth_service.switch_schema(
        switch_to_schema=schema, extra_features=extra_features
    )

    refresh_token = auth_data["refresh_token"]

    @after_this_request
    def after_auth(response):
        set_refresh_cookies(response, refresh_token)

        return response

    return auth_data


@app_auth.route("/authenticate", methods=["POST"])
def auth():
    data = request.get_json()

    email = data.get("email", None)
    password = data.get("password", None)
    schema = data.get("schema", None) if data.get("schema", None) != None else None
    extra_features = data.get("extraFeatures", [])
    refresh_token = None

    try:
        auth_data = auth_service.auth_local(
            email,
            password,
            force_schema=schema,
            extra_features=extra_features,
        )

        refresh_token = auth_data["refresh_token"]
        # temp
        # auth_data.pop("refresh_token")
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    @after_this_request
    def after_auth(response):
        set_refresh_cookies(response, refresh_token)

        return response

    db.session.commit()
    db.session.close()
    db.session.remove()

    return auth_data, status.HTTP_200_OK


@app_auth.route("/auth-provider", methods=["POST"])
def auth_provider():
    data = request.get_json()
    refresh_token = None

    if "schema" not in data or "code" not in data:
        return {
            "status": "error",
            "message": "Parâmetro inválido",
        }, status.HTTP_400_BAD_REQUEST

    try:
        auth_data = auth_service.auth_provider(
            code=data["code"], schema=data["schema"], nonce=data.get("nonce", None)
        )

        refresh_token = auth_data["refresh_token"]
        # temp
        # auth_data.pop("refresh_token")
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    @after_this_request
    def after_auth_provider(response):
        set_refresh_cookies(response, refresh_token)
        return response

    return sessionutils.tryCommit(db, auth_data)


@app_auth.route("/auth-provider/<schema>", methods=["GET"])
def get_auth_provider(schema):
    dbSession.setSchema(schema)

    oauth_config = auth_service.get_oauth_config(schema=schema)

    if oauth_config is None:
        return {"status": "error"}, status.HTTP_404_NOT_FOUND

    return {
        "status": "success",
        "data": {
            "url": oauth_config["auth_url"],
            "loginUrl": oauth_config["login_url"],
            "redirectUri": oauth_config["redirect_uri"],
            "clientId": oauth_config["client_id"],
            "company": oauth_config["company"],
            "flow": (oauth_config["flow"] if "flow" in oauth_config else "implicit"),
            "codeChallengeMethod": (
                oauth_config["code_challenge_method"]
                if "code_challenge_method" in oauth_config
                else None
            ),
        },
    }, status.HTTP_200_OK


@app_auth.route("/refresh-token", methods=["POST"])
@jwt_required(refresh=True, locations=["cookies", "headers"])
def refreshToken():
    current_user = get_jwt_identity()
    current_claims = get_jwt()

    try:
        result = auth_service.refresh_token(
            current_user=current_user, current_claims=current_claims
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return result, status.HTTP_200_OK
