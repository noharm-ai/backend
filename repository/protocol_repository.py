"""Repository: protocol related operations"""

from sqlalchemy import or_

from models.main import db
from models.appendix import Protocol
from models.requests.protocol_request import ProtocolListRequest
from models.enums import ProtocolTypeEnum, ProtocolStatusTypeEnum, NoHarmENV
from config import Config


def list_protocols(request_data: ProtocolListRequest, schema: str) -> list[Protocol]:
    """List protocols"""
    query = db.session.query(Protocol)

    if request_data.active is not None:
        query = query.filter(
            Protocol.status_type == ProtocolStatusTypeEnum.ACTIVE.value
        )

    if request_data.protocolType:
        query = query.filter(Protocol.protocol_type == request_data.protocolType)

    return (
        query.filter(
            or_(Protocol.schema == None, Protocol.schema == schema),
        )
        .order_by(Protocol.name)
        .all()
    )


def get_active_protocols(schema: str, protocol_type: ProtocolTypeEnum):
    """get protocols to apply"""
    query = db.session.query(Protocol).filter(
        Protocol.protocol_type == protocol_type.value,
        or_(Protocol.schema == None, Protocol.schema == schema),
    )

    if Config.ENV == NoHarmENV.PRODUCTION.value:
        query = query.filter(
            Protocol.status_type == ProtocolStatusTypeEnum.ACTIVE.value
        )
    else:
        query = query.filter(
            Protocol.status_type.in_(
                [
                    ProtocolStatusTypeEnum.ACTIVE.value,
                    ProtocolStatusTypeEnum.STAGING.value,
                ]
            )
        )

    return query.all()
