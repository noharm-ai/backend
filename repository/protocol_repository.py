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

    if request_data.protocolTypeList:
        query = query.filter(Protocol.protocol_type.in_(request_data.protocolTypeList))

    if request_data.statusType is not None:
        query = query.filter(Protocol.status_type == request_data.statusType)

    return (
        query.filter(
            or_(Protocol.schema == None, Protocol.schema == schema),
        )
        .order_by(Protocol.name)
        .all()
    )


def get_active_protocols(schema: str, protocol_type_list: list[ProtocolTypeEnum]):
    """get protocols to apply"""

    filter_types = [t.value for t in protocol_type_list]

    query = db.session.query(Protocol).filter(
        Protocol.protocol_type.in_(filter_types),
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
