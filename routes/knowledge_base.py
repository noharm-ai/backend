"""Route: knowledge base articles"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.knowledge_base_request import (
    KnowledgeBaseBrowseRequest,
    KnowledgeBaseManageListRequest,
    KnowledgeBaseUpsertRequest,
)
from services import knowledge_base_service

app_knowledge_base = Blueprint("app_knowledge_base", __name__)


# not an is_admin endpoint: the table is global and the articles are written
# where they are read, in production


@app_knowledge_base.route("/knowledge-base/list", methods=["POST"])
@api_endpoint()
def list_articles():
    """List articles for the maintenance screen"""
    return knowledge_base_service.list_articles(
        request_data=KnowledgeBaseManageListRequest(**(request.get_json() or {}))
    )


@app_knowledge_base.route("/knowledge-base/articles", methods=["POST"])
@api_endpoint()
def browse_articles():
    """List (or search) the published articles for the knowledge base page"""
    return knowledge_base_service.browse_articles(
        request_data=KnowledgeBaseBrowseRequest(**(request.get_json() or {}))
    )


@app_knowledge_base.route("/knowledge-base/training-lessons", methods=["GET"])
@api_endpoint()
def list_training_lessons():
    """List the training lessons an article can be related to"""
    return knowledge_base_service.list_training_lessons()


@app_knowledge_base.route("/knowledge-base/<int:id_article>", methods=["GET"])
@api_endpoint()
def get_article(id_article: int):
    """Get an article with its content"""
    return knowledge_base_service.get_article(id_article=id_article)


@app_knowledge_base.route("/knowledge-base/upsert", methods=["POST"])
@api_endpoint()
def upsert_article():
    """Create or update an article"""
    return knowledge_base_service.upsert_article(
        request_data=KnowledgeBaseUpsertRequest(**(request.get_json() or {}))
    )


@app_knowledge_base.route("/knowledge-base/<int:id_article>/reindex", methods=["POST"])
@api_endpoint()
def reindex_article(id_article: int):
    """Write an article to the n0 vector index again"""
    return knowledge_base_service.reindex_article(id_article=id_article)
