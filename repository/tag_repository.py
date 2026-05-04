"""Repository: tag related operations"""

from models.appendix import Tag
from models.main import db
from models.requests.tag_request import TagListRequest


def list_tags(request_data: TagListRequest) -> list[Tag]:
    """List tags"""
    query = db.session.query(Tag)

    if request_data.active is not None:
        query = query.filter(Tag.active == request_data.active)

    if request_data.tagTypeList:
        query = query.filter(Tag.tag_type.in_(request_data.tagTypeList))

    if request_data.tagType:
        query = query.filter(Tag.tag_type == request_data.tagType)

    return query.order_by(Tag.name).all()
