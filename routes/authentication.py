from flask import Blueprint, request, url_for, jsonify
from flask_api import status
from models.main import *
from models.appendix import *
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)

app_auth = Blueprint('app_auth',__name__)

@app_auth.route("/authenticate", methods=['POST'])
def auth():
    data = request.get_json()

    email = data.get('email', None)
    password = data.get('password', None)

    user = User.authenticate(email, password)

    if user is None:
        return {
            'status': 'error',
            'message': 'Usuário inválido',
        }, status.HTTP_401_UNAUTHORIZED
    else:
        access_token = create_access_token(identity=user.id)
        refresh_token = create_refresh_token(identity=user.id)

        return {
            'status': 'success',
            'userName': user.name,
            'email': user.email,
            'schema': user.schema,
            'roles': user.config['roles'] if user.config and 'roles' in user.config else [],
            'nameUrl': Memory.getNameUrl(user.schema)['value'] if user.permission() else 'http://localhost/{idPatient}',
            'access_token': access_token,
            'refresh_token': refresh_token
        }, status.HTTP_200_OK


@app_auth.route("/refresh-token", methods=['POST'])
@jwt_refresh_token_required
def refreshToken():
    current_user = get_jwt_identity()
    access_token = create_access_token(identity=current_user)
    return {'access_token': access_token}