from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services import memory_service

app_mem = Blueprint("app_mem", __name__)


@app_mem.route("/memory", methods=["GET"])
@api_endpoint()
def get_memories():
    """List all editable memory records."""
    return memory_service.get_editable_memories()


@app_mem.route("/memory/id/<int:idMemory>", methods=["GET"])
@api_endpoint()
def get_memory_by_id(idMemory: int):
    """Get a single memory record by its ID."""
    return memory_service.get_memory_by_id(id=idMemory)


@app_mem.route("/memory/<string:kind>", methods=["GET"])
@api_endpoint()
def getMemory(kind):
    """Get all memory records of a given kind."""
    return memory_service.get_memory_by_kind(kind=kind)


@app_mem.route("/memory/", methods=["PUT"])
@app_mem.route("/memory", methods=["PUT"])
@app_mem.route("/memory/<int:idMemory>", methods=["PUT"])
@api_endpoint()
def save_memory(idMemory=None):
    """Create or update a memory record."""
    data = request.get_json()

    mem = memory_service.save_memory(idMemory, data.get("type"), data.get("value"))

    return mem.key


@app_mem.route("/memory/custom-forms", methods=["PUT"])
@app_mem.route("/memory/custom-forms/<int:idMemory>", methods=["PUT"])
@api_endpoint()
def save_custom_form(idMemory=None):
    """Create or update a custom-forms memory record."""
    data = request.get_json() or {}

    mem = memory_service.save_custom_form(id=idMemory, value=data.get("value"))

    return mem.key


@app_mem.route("/memory/unique/<string:kind>", methods=["PUT"])
@api_endpoint()
def save_memory_unique(kind):
    """Create or update a memory record, ensuring only one record exists per kind."""
    data = request.get_json()

    mem = memory_service.save_unique_memory(kind, data.get("value"))

    return mem.key
