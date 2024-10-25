import os
import logging
from flask import Flask
from flask_jwt_extended import JWTManager
from flask_cors import CORS

from models.main import db, mail
from config import Config
from models.enums import NoHarmENV
from utils import status

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
from routes.user_admin import app_user_admin
from routes.prescription_crud import app_pres_crud
from routes.drugs import app_drugs
from routes.names import app_names
from routes.summary import app_summary
from routes.support import app_support
from routes.conciliation import app_conciliation
from routes.admin.admin_frequency import app_admin_freq
from routes.admin.admin_intervention_reason import app_admin_interv
from routes.admin.admin_memory import app_admin_memory
from routes.admin.admin_drug import app_admin_drug
from routes.admin.admin_integration import app_admin_integration
from routes.admin.admin_integration_remote import app_admin_integration_remote
from routes.admin.admin_segment import app_admin_segment
from routes.admin.admin_exam import app_admin_exam
from routes.admin.admin_unit_conversion import app_admin_unit_conversion
from routes.admin.admin_substance import app_admin_subs
from routes.admin.admin_relation import app_admin_relation
from routes.reports.reports_general import app_rpt_general
from routes.reports.reports_config_rpt import app_rpt_config
from routes.reports.reports_culture import app_rpt_culture
from routes.reports.reports_antimicrobial import app_rpt_antimicrobial

os.environ["TZ"] = "America/Sao_Paulo"

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = Config.POTGRESQL_CONNECTION_STRING
app.config["SQLALCHEMY_BINDS"] = {"report": Config.REPORT_CONNECTION_STRING}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 250,
    "pool_pre_ping": True,
    "pool_size": 20,
    "max_overflow": 30,
}
app.config["JWT_SECRET_KEY"] = Config.SECRET_KEY
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = Config.JWT_ACCESS_TOKEN_EXPIRES
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = Config.JWT_REFRESH_TOKEN_EXPIRES
app.config["JWT_COOKIE_SAMESITE"] = "Lax"
app.config["JWT_COOKIE_SECURE"] = True
app.config["JWT_REFRESH_COOKIE_PATH"] = "/refresh-token"
app.config["JWT_REFRESH_CSRF_COOKIE_PATH"] = "/refresh-token"
app.config["JWT_COOKIE_CSRF_PROTECT"] = False
app.config["MAIL_SERVER"] = "email-smtp.sa-east-1.amazonaws.com"
app.config["MAIL_PORT"] = 465
app.config["MAIL_USE_SSL"] = True
app.config["MAIL_USERNAME"] = Config.MAIL_USERNAME
app.config["MAIL_PASSWORD"] = Config.MAIL_PASSWORD

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
app.register_blueprint(app_summary)
app.register_blueprint(app_support)
app.register_blueprint(app_conciliation)

app.register_blueprint(app_user_admin)
app.register_blueprint(app_pres_crud)

app.register_blueprint(app_admin_freq)
app.register_blueprint(app_admin_interv)
app.register_blueprint(app_admin_memory)
app.register_blueprint(app_admin_drug)
app.register_blueprint(app_admin_integration)
app.register_blueprint(app_admin_integration_remote)
app.register_blueprint(app_admin_segment)
app.register_blueprint(app_admin_exam)
app.register_blueprint(app_admin_unit_conversion)
app.register_blueprint(app_admin_subs)
app.register_blueprint(app_admin_relation)

app.register_blueprint(app_rpt_general)
app.register_blueprint(app_rpt_culture)
app.register_blueprint(app_rpt_antimicrobial)
app.register_blueprint(app_rpt_config)

CORS(app, origins=[Config.MAIL_HOST], supports_credentials=True)

if Config.ENV != NoHarmENV.PRODUCTION.value:
    logging.basicConfig()
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
    logging.getLogger("noharm.backend").setLevel(logging.DEBUG)


@app.route("/version", methods=["GET"])
def getVersion():
    return {"status": "success", "data": Config.VERSION}, status.HTTP_200_OK


@app.route("/frontend-version", methods=["GET"])
def frontend_version():
    return {"status": "success", "data": Config.FRONTEND_VERSION}, status.HTTP_200_OK


if __name__ == "__main__":
    if Config.ENV == NoHarmENV.DEVELOPMENT.value:
        app.debug = True
    else:
        app.debug = False

    app.run(host="0.0.0.0")


@app.after_request
def add_security_headers(response):
    headers = {
        "strict-transport-security": ["max-age=63072000", "includeSubDomains"],
        "content-security-policy": ["default-src 'none'", "frame-ancestors 'none'"],
        "x-frame-options": ["SAMEORIGIN"],
        "x-xss-protection": ["1", "mode=block"],
        "x-content-type-options": ["nosniff"],
        "referrer-policy": ["same-origin"],
    }
    for key, content in headers.items():
        response.headers[key] = ";".join(content)
    return response


# register the error handler
@app.errorhandler(Exception)
def handle_exception(e):
    logger = logging.getLogger("noharm.backend")
    logger.exception(str(e))

    return {"status": "error", "message": "Erro inesperado"}, 500
