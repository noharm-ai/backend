"""Service: simple list records operations"""

from repository import lists_repository
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.READ_BASIC_FEATURES)
def list_icds():
    """List icds"""
    query_results = lists_repository.list_icds()

    results = []
    for item in query_results:
        results.append(
            {
                "name": f"{item.id_str} - {item.name}",
                "id": item.id_str,
            }
        )

    return results
