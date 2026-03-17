from flask import Blueprint, request

from models.requests.knowledge_base_request import (
    KnowledgeBaseListRequest,
    KnowledgeBaseUpsertRequest,
)
from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_knowledge_base_service

app_admin_knowledge_base = Blueprint("app_admin_knowledge_base", __name__)


@app_admin_knowledge_base.route("/admin/knowledge-base/list", methods=["POST"])
@api_endpoint()
def get_knowledge_base():
    return admin_knowledge_base_service.get_knowledge_base(
        request_data=KnowledgeBaseListRequest(**request.get_json())
    )


@app_admin_knowledge_base.route("/admin/knowledge-base/upsert", methods=["POST"])
@api_endpoint()
def upsert():
    return admin_knowledge_base_service.upsert_knowledge_base(
        request_data=KnowledgeBaseUpsertRequest(**request.get_json())
    )
