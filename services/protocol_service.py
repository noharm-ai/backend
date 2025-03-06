"""Service: protocol related operations"""

from repository import protocol_repository
from models.requests.protocol_request import ProtocolListRequest
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.READ_BASIC_FEATURES)
def list_protocols(request_data: ProtocolListRequest):
    """List protocols and filter"""
    results = protocol_repository.list_protocols(request_data=request_data)

    protocols = []
    for item in results:
        protocols.append(
            {
                "id": item.id,
                "name": item.name,
                "protocolType": item.protocol_type,
                "active": item.active,
            }
        )

    return protocols
