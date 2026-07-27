"""Service: simple list records operations"""

from repository import lists_repository
from services import memory_service
from models.enums import MemoryEnum
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import status


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


@has_permission(Permission.READ_BASIC_FEATURES)
def find_icds(term):
    """Search icds by code or description"""
    if term == "" or term is None:
        raise ValidationError(
            "Busca inválida",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    query_results = lists_repository.find_icds(term)

    return [{"id": item.id_str, "name": item.name} for item in query_results]


@has_permission(Permission.READ_BASIC_FEATURES)
def list_routes():
    """List routes stored in the map-routes memory"""
    map_routes = memory_service.get_memory(MemoryEnum.MAP_ROUTES.value)

    results = []
    if map_routes and map_routes.value:
        for r in map_routes.value:
            if isinstance(r, dict) and r.get("id") is not None:
                results.append({"id": r.get("id"), "name": r.get("value")})

    return results


@has_permission(Permission.READ_BASIC_FEATURES)
def find_icds_by_ids(ids):
    """Resolve icds by their codes"""
    if not ids:
        return []

    query_results = lists_repository.find_icds_by_ids(ids)

    return [{"id": item.id_str, "name": item.name} for item in query_results]
