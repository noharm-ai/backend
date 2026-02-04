"""Route: names proxy"""

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from models.main import User, dbSession
from services import name_service
from utils import logger, status

app_names = Blueprint("app_names", __name__)


@app_names.route("/names/<int:idPatient>", methods=["GET"])
@jwt_required()
def proxy_name(idPatient):
    """Proxy get single name"""
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        response = name_service.get_patient_name(id_patient=idPatient, user=user)

        return response, status.HTTP_200_OK if response.get(
            "status"
        ) == "success" else status.HTTP_400_BAD_REQUEST
    except Exception as e:
        logger.backend_logger.error(
            f"Error getting patient name: {str(e)}", exc_info=True
        )
        return {
            "status": "error",
            "idPatient": int(idPatient),
            "name": f"Paciente {str(int(idPatient))}",
        }, status.HTTP_400_BAD_REQUEST


@app_names.route("/names", methods=["POST"])
@jwt_required()
def proxy_multiple():
    """Proxy get multiple names"""
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    data = request.get_json()
    ids_list = data.get("patients", [])

    try:
        names = name_service.get_multiple_patient_names(ids_list=ids_list, user=user)
        return names, status.HTTP_200_OK
    except Exception as e:
        logger.backend_logger.error(
            f"Error getting multiple patient names: {str(e)}", exc_info=True
        )
        return [], status.HTTP_500_INTERNAL_SERVER_ERROR


@app_names.route("/names/auth-token", methods=["GET"])
@jwt_required()
def auth_token():
    """Get internal token"""
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        token = name_service.generate_internal_token(user=user)
        return {"status": "success", "data": token}, status.HTTP_200_OK
    except Exception as e:
        logger.backend_logger.error(
            f"Error generating auth token: {str(e)}", exc_info=True
        )
        return {
            "status": "error",
            "message": str(e),
        }, status.HTTP_400_BAD_REQUEST


@app_names.route("/names/search/<string:term>", methods=["GET"])
@jwt_required()
def search_name(term):
    """Inverted name search"""
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        results = name_service.search_patient_by_name(search_term=term, user=user)
        return {
            "status": "success",
            "data": results,
        }, status.HTTP_200_OK
    except Exception as e:
        logger.backend_logger.error(
            f"Error searching patient name: {str(e)}", exc_info=True
        )
        return {"status": "error", "data": []}, status.HTTP_200_OK
