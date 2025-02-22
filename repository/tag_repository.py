"""Repository: tag related operations"""

from models.main import db
from models.appendix import Tag
from models.requests.tag_request import TagListRequest


def list_tags(request_data: TagListRequest) -> list[Tag]:
    """List tags"""
    query = db.session.query(Tag)

    if request_data.active != None:
        query = query.filter(Tag.active == request_data.active)

    if request_data.tagType:
        query = query.filter(Tag.tag_type == request_data.tagType)

    return query.order_by(Tag.tag_type, Tag.name).all()
