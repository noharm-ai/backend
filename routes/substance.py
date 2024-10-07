from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services import substance_service

app_sub = Blueprint("app_sub", __name__)


@app_sub.route("/substance", methods=["GET"])
@api_endpoint()
def getSubstance():
    return substance_service.get_substances()


@app_sub.route("/substance/handling", methods=["GET"])
@api_endpoint()
def get_substance_handling():
    return substance_service.get_substance_handling(
        sctid=request.args.get("sctid", None),
        alert_type=request.args.get("alertType"),
    )


@app_sub.route("/substance/find", methods=["GET"])
@api_endpoint()
def find_substance():
    term = request.args.get("term", "")

    return substance_service.find_substance(term)


@app_sub.route("/substance/class/find", methods=["GET"])
@api_endpoint()
def find_substance_class():
    term = request.args.get("term", "")

    return substance_service.find_substance_class(term)


@app_sub.route("/substance/<int:idSubstance>/relation", methods=["GET"])
@api_endpoint()
def getRelations(idSubstance):
    return substance_service.get_substance_relations(sctid=idSubstance)


@app_sub.route("/substance/class", methods=["GET"])
@api_endpoint()
def get_substance_class():
    return substance_service.get_substance_classes()
