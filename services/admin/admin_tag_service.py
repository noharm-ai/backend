from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Tag
from models.enums import TagTypeEnum
from models.main import User, db
from models.requests.tag_request import TagListRequest, TagUpsertRequest
from repository import tag_repository
from utils import dateutils, status

MAX_TAG_CHARS = 40


@has_permission(Permission.READ_PRESCRIPTION)
def get_tags(request_data: TagListRequest, user_permissions: list[Permission]):
    """List tags filtered by allowed tag types based on user permissions."""
    tag_types = [TagTypeEnum.PATIENT.value]

    if Permission.READ_NAV in user_permissions:
        tag_types.append(TagTypeEnum.PATIENT_NAVIGATION.value)

    request_data.tagTypeList = tag_types

    results = tag_repository.list_tags(request_data=request_data)

    return [_to_dto(item) for item in results]


@has_permission(Permission.WRITE_TAGS, Permission.WRITE_PATIENT_TAGS)
def upsert_tag(
    request_data: TagUpsertRequest,
    user_context: User,
    user_permissions: list[Permission],
):
    if not request_data.name or len(request_data.name) > MAX_TAG_CHARS:
        raise ValidationError(
            f"Limite de caracteres para a Tag foi atingido ({MAX_TAG_CHARS})",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if Permission.WRITE_TAGS not in user_permissions:
        if request_data.tagType != TagTypeEnum.PATIENT_NAVIGATION.value:
            raise ValidationError(
                "Permissão insuficiente para este tipo de marcador",
                "errors.businessRules",
                status.HTTP_403_FORBIDDEN,
            )

        if not request_data.name.upper().startswith("NAVEGACAO_"):
            raise ValidationError(
                "O nome do marcador deve iniciar com 'NAVEGACAO_'",
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
            "Já existe um marcador com este nome",
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
