from flask import request, url_for, jsonify
from flask_api import FlaskAPI, status, exceptions
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from models.main import db, mail
from config import Config
from flask_cors import CORS
from routes.authentication import app_auth
from routes.outlier import app_out
from routes.prescription import app_pres
from routes.segment import app_seg
from routes.outlier_generate import app_gen
from routes.intervention import app_itrv
from routes.static import app_stc
from routes.substance import app_sub
from routes.memory import app_mem
from routes.patient import app_pat
from routes.user import app_usr
from routes.notes import app_note
from routes.user_crud import app_user_crud
from routes.prescription_crud import app_pres_crud
from routes.drugs import app_drugs
from routes.names import app_names
from routes.admin.frequency import app_admin_freq
import os

os.environ['TZ'] = 'America/Sao_Paulo'

app = FlaskAPI(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = Config.POTGRESQL_CONNECTION_STRING
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = { "pool_recycle" : 500, "pool_pre_ping": True, "pool_size": 20, "max_overflow": 30 }
app.config['JWT_SECRET_KEY'] = Config.SECRET_KEY
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = Config.JWT_ACCESS_TOKEN_EXPIRES
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = Config.JWT_REFRESH_TOKEN_EXPIRES
app.config['MAIL_SERVER'] = 'email-smtp.sa-east-1.amazonaws.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = Config.MAIL_USERNAME
app.config['MAIL_PASSWORD'] = Config.MAIL_PASSWORD

jwt = JWTManager(app)
db.init_app(app)
mail.init_app(app)

app.register_blueprint(app_auth)
app.register_blueprint(app_out)
app.register_blueprint(app_pres)
app.register_blueprint(app_seg)
app.register_blueprint(app_gen)
app.register_blueprint(app_itrv)
app.register_blueprint(app_stc)
app.register_blueprint(app_sub)
app.register_blueprint(app_mem)
app.register_blueprint(app_pat)
app.register_blueprint(app_usr)
app.register_blueprint(app_note)
app.register_blueprint(app_drugs)
app.register_blueprint(app_names)

app.register_blueprint(app_user_crud)
app.register_blueprint(app_pres_crud)

app.register_blueprint(app_admin_freq)

CORS(app)

@app.route("/version", methods=['GET'])
def getVersion():
    return {
        'status': 'success',
        'data': 'v1.61-beta'
    }, status.HTTP_200_OK

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0')

@app.after_request
def add_security_headers(response):
    headers = {
        'strict-transport-security': [
            'max-age=63072000',
            'includeSubDomains'
        ],
        'content-security-policy': [
            'default-src \'none\'',
            'frame-ancestors \'none\''
        ],
        'x-frame-options': ['SAMEORIGIN'],
        'x-xss-protection': [ '1', 'mode=block' ],
        'x-content-type-options': ['nosniff'],
        'referrer-policy': ['same-origin'],
    }
    for (key, content) in headers.items():
        response.headers[key] = ';'.join(content)
    return response
