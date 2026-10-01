"""Route: news (novidades)"""

from flask import Blueprint

from decorators.api_endpoint_decorator import api_endpoint
from services import news_service

app_news = Blueprint("app_news", __name__)


@app_news.route("/news", methods=["GET"])
@api_endpoint()
def list_news():
    """List published news, most recent first, without content"""
    return news_service.list_news()


@app_news.route("/news/<int:id_news>", methods=["GET"])
@api_endpoint()
def get_news(id_news: int):
    """Get a published news record with its content"""
    return news_service.get_news(id_news=id_news)
