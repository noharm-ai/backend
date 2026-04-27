"""Service: tag related operations"""

from flask import g

from decorators.has_permission_decorator import Permission, has_permission
from models.enums import TagTypeEnum
from models.requests.tag_request import TagListRequest
from repository import tag_repository


@has_permission(Permission.READ_BASIC_FEATURES)
def list_tags(request_data: TagListRequest):
    """List tags and filter"""

    if str(TagTypeEnum.PATIENT.value) == request_data.tagType:
        request_data.tagType = None
        request_data.tagTypeList = [TagTypeEnum.PATIENT.value]

        user_permissions = g.get("user_permissions", [])
        if Permission.READ_NAV in user_permissions:
            request_data.tagTypeList.append(TagTypeEnum.PATIENT_NAVIGATION.value)

    results = tag_repository.list_tags(request_data=request_data)

    tags = []
    for item in results:
        tags.append(
            {"name": item.name, "tagType": item.tag_type, "active": item.active}
        )

    return tags
