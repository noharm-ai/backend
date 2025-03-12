"""Service: protocol related operations"""

from repository import protocol_repository
from models.main import User
from models.requests.protocol_request import ProtocolListRequest
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.READ_BASIC_FEATURES)
def list_protocols(request_data: ProtocolListRequest, user_context: User):
    """List protocols and filter"""
    results = protocol_repository.list_protocols(
        request_data=request_data, schema=user_context.schema
    )

    protocols = []
    for item in results:
        protocols.append(
            {
                "id": item.id,
                "name": item.name,
                "protocolType": item.protocol_type,
                "status": item.status_type,
            }
        )

    return protocols
