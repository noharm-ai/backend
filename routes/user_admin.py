"""Route: route for user admin operations"""

from flask import Blueprint, request

from services import user_service, user_admin_service
from decorators.api_endpoint_decorator import api_endpoint


app_user_admin = Blueprint("app_user_admin", __name__)


@app_user_admin.route("/user-admin/upsert", methods=["POST"])
@app_user_admin.route("/editUser", methods=["POST"])
@api_endpoint()
def upsert_user():
    """Upsert user"""
    data = request.get_json()

    return user_admin_service.upsert_user(data=data)


@app_user_admin.route("/user-admin/list", methods=["GET"])
@app_user_admin.route("/users", methods=["GET"])
@api_endpoint()
def get_users():
    """Get users list"""
    return user_admin_service.get_user_list()


@app_user_admin.route("/user-admin/manager-list", methods=["GET"])
@api_endpoint()
def get_user_managers():
    """Get active user managers list"""
    return user_admin_service.get_user_manager_list()


@app_user_admin.route("/user-admin/contact-list", methods=["GET"])
@api_endpoint()
def get_contact_list():
    """Get active users of a contactable role, to know who to ask for a change"""
    return user_admin_service.get_contact_list(role=request.args.get("role", None))


@app_user_admin.route("/user-admin/reset-token", methods=["POST"])
@app_user_admin.route("/user/reset-token", methods=["POST"])
@api_endpoint()
def get_reset_token():
    """Get reset token"""
    data = request.get_json()

    return user_service.admin_get_reset_token(data.get("idUser", None))


@app_user_admin.route("/user-admin/send-reset-email", methods=["POST"])
@api_endpoint()
def send_reset_password_email():
    """Send a password reset link to the user's email"""
    data = request.get_json()

    return user_service.send_reset_password_email(id_user=data.get("idUser", None))


@app_user_admin.route("/user-admin/reset-history/<int:id_user>", methods=["GET"])
@api_endpoint()
def get_reset_password_history(id_user: int):
    """Get a user's password reset request history"""
    return user_service.get_reset_password_history(id_user=id_user)
