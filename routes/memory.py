from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services import memory_service

app_mem = Blueprint("app_mem", __name__)


@app_mem.route("/memory/<string:kind>", methods=["GET"])
@api_endpoint()
def getMemory(kind):
    return memory_service.get_memory_by_kind(kind=kind)


@app_mem.route("/memory/", methods=["PUT"])
@app_mem.route("/memory", methods=["PUT"])
@app_mem.route("/memory/<int:idMemory>", methods=["PUT"])
@api_endpoint()
def save_memory(idMemory=None):
    data = request.get_json()

    mem = memory_service.save_memory(idMemory, data.get("type"), data.get("value"))

    return mem.key


@app_mem.route("/memory/custom-forms", methods=["PUT"])
@app_mem.route("/memory/custom-forms/<int:idMemory>", methods=["PUT"])
@api_endpoint()
def save_custom_form(idMemory=None):
    data = request.get_json() or {}

    mem = memory_service.save_custom_form(id=idMemory, value=data.get("value"))

    return mem.key


@app_mem.route("/memory/unique/<string:kind>", methods=["PUT"])
@api_endpoint()
def save_memory_unique(kind):
    data = request.get_json()

    mem = memory_service.save_unique_memory(kind, data.get("value"))

    return mem.key
