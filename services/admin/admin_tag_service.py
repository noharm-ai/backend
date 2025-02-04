from utils import status
from datetime import datetime

from models.main import db, User
from models.appendix import Tag
from models.requests.tag_request import TagListRequest, TagUpsertRequest
from repository import tag_repository
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import dateutils

MAX_TAG_CHARS = 40


@has_permission(Permission.READ_PRESCRIPTION)
def get_tags(request_data: TagListRequest):
    results = tag_repository.list_tags(request_data=request_data)

    tags = []
    for item in results:
        tags.append(_to_dto(item))

    return tags


@has_permission(Permission.WRITE_TAGS)
def upsert_tag(request_data: TagUpsertRequest, user_context: User):
    if not request_data.name or len(request_data.name) > MAX_TAG_CHARS:
        raise ValidationError(
            f"Limite de caracteres para a Tag foi atingido ({MAX_TAG_CHARS})",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    tag = (
        db.session.query(Tag)
        .filter(
            Tag.name == request_data.name.upper(), Tag.tag_type == request_data.tagType
        )
        .first()
    )

    if not tag:
        tag = Tag()
        tag.name = request_data.name.upper()
        tag.tag_type = request_data.tagType
        tag.created_at = datetime.today()
        tag.created_by = user_context.id
        db.session.add(tag)
    elif request_data.new:
        raise ValidationError(
            f"Já existe um marcador com este nome",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    tag.active = request_data.active
    tag.updated_at = datetime.today()
    tag.updated_by = user_context.id

    db.session.flush()

    return _to_dto(tag)


def _to_dto(tag: Tag):

    return {
        "name": tag.name,
        "tagType": tag.tag_type,
        "active": tag.active,
        "createdAt": dateutils.to_iso(tag.created_at),
        "updatedAt": dateutils.to_iso(tag.updated_at),
    }
