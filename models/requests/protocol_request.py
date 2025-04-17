"""Request model: protocol"""

from typing import Optional
from pydantic import BaseModel


class ProtocolListRequest(BaseModel):
    """Protocol request parameters"""

    active: Optional[bool] = None
    protocolType: Optional[str] = None
    protocolTypeList: list[int] = None
    statusType: Optional[int] = None


class ProtocolConfig(BaseModel):
    """Protocol: structure of a protocol configuration"""

    result: dict
    trigger: str
    variables: list[dict]


class ProtocolUpsertRequest(BaseModel):
    """Protocol create/update request params"""

    id: int = None
    name: str
    protocolType: int
    statusType: int
    config: ProtocolConfig
