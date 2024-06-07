from flask import (
    Blueprint,
    request,
    url_for,
    jsonify,
    after_this_request,
)
from utils import status
from models.main import *
from models.appendix import *
from models.prescription import *
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity,
    get_jwt,
    set_refresh_cookies,
)

from models.enums import MemoryEnum, IntegrationStatusEnum
from services import auth_service, memory_service, permission_service
from services.admin import integration_status_service
from exception.validation_error import ValidationError

app_auth = Blueprint("app_auth", __name__)


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


@app_auth.route("/authenticate", methods=["POST"])
def auth():
    data = request.get_json()

    email = data.get("email", None)
    password = data.get("password", None)
    schema = data.get("schema", None) if data.get("schema", None) != None else None
    default_roles = data.get("defaultRoles", [])
    extra_features = data.get("extraFeatures", [])
    run_as_basic_user = data.get("runAsBasicUser", False)
    refresh_token = None

    try:
        auth_data = auth_service.auth_local(
            email,
            password,
            force_schema=schema,
            default_roles=default_roles,
            run_as_basic_user=run_as_basic_user,
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
        auth_data = auth_service.auth_provider(code=data["code"], schema=data["schema"])

        auth_data["oauth"] = True
        refresh_token = auth_data["refresh_token"]
        # temp
        # auth_data.pop("refresh_token")
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    @after_this_request
    def after_auth_provider(response):
        set_refresh_cookies(response, refresh_token)
        return response

    return tryCommit(db, auth_data)


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
            "clientSecret": oauth_config["client_secret"],
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

    if "schema" in current_claims:
        claims = {
            "schema": current_claims["schema"],
            "config": current_claims["config"],
        }
    else:
        return {"status": "error"}, status.HTTP_401_UNAUTHORIZED

    user = db.session.query(User).filter(User.id == get_jwt_identity()).first()
    if user == None:
        return {
            "status": "error",
            "message": "Usuário inválido",
        }, status.HTTP_401_UNAUTHORIZED

    if user.active == False:
        return {
            "status": "error",
            "message": "Usuário inativo",
        }, status.HTTP_401_UNAUTHORIZED

    integration_status = integration_status_service.get_integration_status(
        current_claims["schema"]
    )
    if (
        integration_status == IntegrationStatusEnum.CANCELED.value
        and not permission_service.has_maintainer_permission(user)
    ):
        return {
            "status": "error",
            "message": "Cliente desativado",
        }, status.HTTP_401_UNAUTHORIZED

    access_token = create_access_token(identity=current_user, additional_claims=claims)

    return {"access_token": access_token}
