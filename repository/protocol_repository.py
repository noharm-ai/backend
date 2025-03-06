"""Repository: protocol related operations"""

from sqlalchemy import or_

from models.main import db
from models.appendix import Protocol
from models.requests.protocol_request import ProtocolListRequest
from models.enums import ProtocolTypeEnum


def list_protocols(request_data: ProtocolListRequest) -> list[Protocol]:
    """List protocols"""
    query = db.session.query(Protocol)

    if request_data.active is not None:
        query = query.filter(Protocol.active == request_data.active)

    if request_data.protocolType:
        query = query.filter(Protocol.protocol_type == request_data.protocolType)

    return query.order_by(Protocol.name).all()


def get_active_protocols(schema: str, protocol_type: ProtocolTypeEnum):
    """get protocols to apply"""
    return (
        db.session.query(Protocol)
        .filter(
            Protocol.protocol_type == protocol_type.value,
            Protocol.active == True,
            or_(Protocol.schema == None, Protocol.schema == schema),
        )
        .all()
    )
