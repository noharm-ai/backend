import os
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from models.main import *
from services import summary_service, llm_service
from exception.validation_error import ValidationError

app_summary = Blueprint("app_summary", __name__)


@app_summary.route("/summary/<int:admission_number>", methods=["GET"])
@jwt_required()
def get_structured_info(admission_number):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    mock = request.args.get("mock", False)

    try:
        result = summary_service.get_structured_info(
            admission_number=admission_number, user=user, mock=mock
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {"status": "success", "data": result}, status.HTTP_200_OK


@app_summary.route("/summary/prompt", methods=["POST"])
@jwt_required()
def prompt():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    data = request.get_json()

    try:
        result = llm_service.prompt(data.get("messages", []), options=data)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {"status": "success", "data": result}, status.HTTP_200_OK
