from flask import Blueprint

from decorators.api_endpoint_decorator import api_endpoint
from services import segment_service

app_seg = Blueprint("app_seg", __name__)


@app_seg.route("/segments", methods=["GET"])
@api_endpoint()
def getSegments():
    results = segment_service.get_segments()

    list = []
    for i in results:
        list.append(
            {
                "id": i.id,
                "description": i.description,
                "status": i.status,
                "type": i.type,
                "cpoe": i.cpoe,
            }
        )

    return list


@app_seg.route("/segments/departments", methods=["GET"])
@api_endpoint()
def get_segment_departments():
    return segment_service.get_segment_departments()
