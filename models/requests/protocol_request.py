"""Request model: protocol"""

from typing import Optional
from pydantic import BaseModel


class ProtocolListRequest(BaseModel):
    """Protocol request parameters"""

    active: Optional[bool] = None
    protocolType: Optional[str] = None
    protocolTypeList: list[int] = None
