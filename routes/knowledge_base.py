"""Route: knowledge base (help center articles)"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.knowledge_base_request import KnowledgeBaseSearchRequest
from services import knowledge_base_service

app_knowledge_base = Blueprint("app_knowledge_base", __name__)


@app_knowledge_base.route("/knowledge-base/articles", methods=["GET"])
@api_endpoint()
def list_articles():
    """List every published article, without content"""
    return knowledge_base_service.list_articles()


@app_knowledge_base.route("/knowledge-base/articles/<int:id_article>", methods=["GET"])
@api_endpoint()
def get_article(id_article: int):
    """Get a published article with its content and related items"""
    return knowledge_base_service.get_article(id_article=id_article)


@app_knowledge_base.route("/knowledge-base/search", methods=["POST"])
@api_endpoint()
def search_articles():
    """Semantic search over the published articles"""
    return knowledge_base_service.search_articles(
        request_data=KnowledgeBaseSearchRequest(**(request.get_json() or {}))
    )
