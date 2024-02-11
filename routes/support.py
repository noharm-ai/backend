from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from models.main import *
from services import support_service
from exception.validation_error import ValidationError

app_support = Blueprint("app_support", __name__)


@app_support.route("/support/create-ticket", methods=["POST"])
@jwt_required()
def create_ticket():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        result = support_service.create_ticket(user=user, from_url="http://example.com")
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {"status": "success", "data": result}, status.HTTP_200_OK
