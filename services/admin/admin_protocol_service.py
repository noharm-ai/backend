"""Service: admin protocol operations"""

from decorators.has_permission_decorator import has_permission, Permission
from repository import protocol_repository
from models.main import User
from models.requests.protocol_request import ProtocolListRequest
from utils import dateutils


@has_permission(Permission.READ_PROTOCOLS)
def list_protocols(request_data: ProtocolListRequest, user_context: User):
    """List schema protocols"""
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
                "config": item.config,
                "statusType": item.status_type,
                "createdAt": dateutils.to_iso(item.created_at),
                "updatedAt": dateutils.to_iso(item.updated_at),
            }
        )

    return protocols
