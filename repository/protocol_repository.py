"""Repository: protocol related operations"""

from models.main import db
from models.appendix import Protocol
from models.requests.protocol_request import ProtocolListRequest


def list_protocols(request_data: ProtocolListRequest) -> list[Protocol]:
    """List protocols"""
    query = db.session.query(Protocol)

    if request_data.active != None:
        query = query.filter(Protocol.active == request_data.active)

    if request_data.protocolType:
        query = query.filter(Protocol.protocol_type == request_data.protocolType)

    return query.order_by(Protocol.name).all()
