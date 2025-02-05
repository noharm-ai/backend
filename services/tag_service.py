from repository import tag_repository
from models.requests.tag_request import TagListRequest
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.READ_PRESCRIPTION)
def list_tags(request_data: TagListRequest):
    results = tag_repository.list_tags(request_data=request_data)

    tags = []
    for item in results:
        tags.append(
            {"name": item.name, "tagType": item.tag_type, "active": item.active}
        )

    return tags
