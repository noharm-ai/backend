from flask import request, url_for, jsonify
from flask_api import FlaskAPI, status, exceptions
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from models import db, User
from config import Config
from flask_cors import CORS
from routes.authentication import app_auth
from routes.outlier import app_out
from routes.prescription import app_pres
from routes.segment import app_seg
from routes.outlier_generate import app_gen

app = FlaskAPI(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = Config.POTGRESQL_CONNECTION_STRING
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_POOL_RECYCLE'] = 299
app.config['SQLALCHEMY_POOL_TIMEOUT'] = 20
app.config['JWT_SECRET_KEY'] = Config.SECRET_KEY
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = Config.JWT_ACCESS_TOKEN_EXPIRES
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = Config.JWT_REFRESH_TOKEN_EXPIRES

jwt = JWTManager(app)
db.init_app(app)

app.register_blueprint(app_auth)
app.register_blueprint(app_out)
app.register_blueprint(app_pres)
app.register_blueprint(app_seg)
app.register_blueprint(app_gen)

CORS(app)

@app.route("/user/name-url", methods=['GET'])
@jwt_required
def getNameUrl():
    user = User.find(get_jwt_identity())

    return {
        'status': 'success',
        'url': user.nameUrl
    }, status.HTTP_200_OK 


@app.route("/patient-name/<int:idPatient>", methods=['GET'])
def getName(idPatient):
    return {
        'status': 'success',
        'idPatient': idPatient,
        'name': 'Fulano da Silva e Santos'
    }, status.HTTP_200_OK


if __name__ == "__main__":
    app.run(debug=True)
