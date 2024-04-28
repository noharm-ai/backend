from flask import current_app
from os import getenv
import requests
from flask import Blueprint
from flask_jwt_extended import jwt_required, get_jwt
import logging
from http.client import HTTPConnection

app_names = Blueprint("app_names", __name__)


@app_names.route("/names/<int:idPatient>", methods=["GET"])
@jwt_required()
def proxy_name(idPatient):
    return "not implemented"

    # HTTPConnection.debuglevel = 1
    # requests_log = logging.getLogger("requests.packages.urllib3")
    # requests_log.setLevel(logging.DEBUG)
    # requests_log.propagate = True

    # claims = get_jwt()
    # schema = claims["schema"].upper()
    # to_url = getenv(schema + '_PROXY_URL')
    # header_env = getenv(schema + '_PROXY_HEADERS')
    # headers = {}

    # #split headers
    # for h in header_env.split("@@"):
    #     item = h.split(":")
    #     headers[item[0]] = item[1]

    # response = requests.get(\
    #     url=to_url.replace("{idPatient}", str(idPatient)),\
    #     headers=headers)

    # current_app.logger.info('proxyresponse %s', response.content)

    # return response.json()
