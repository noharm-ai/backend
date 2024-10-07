from flask import Blueprint, request

from services import user_service, user_admin_service
from decorators.api_endpoint_decorator import api_endpoint


app_user_admin = Blueprint("app_user_admin", __name__)


@app_user_admin.route("/user-admin/upsert", methods=["POST"])
@app_user_admin.route("/editUser", methods=["POST"])
@api_endpoint()
def upsert_user():
    data = request.get_json()

    return user_admin_service.upsert_user(data=data)


@app_user_admin.route("/user-admin/list", methods=["GET"])
@app_user_admin.route("/users", methods=["GET"])
@api_endpoint()
def getUsers():
    return user_admin_service.get_user_list()


@app_user_admin.route("/user-admin/reset-token", methods=["POST"])
@app_user_admin.route("/user/reset-token", methods=["POST"])
@api_endpoint()
def get_reset_token():
    data = request.get_json()

    return user_service.admin_get_reset_token(data.get("idUser", None))
