"""Request models: admin global memory related"""

from pydantic import BaseModel


class GlobalMemoryItensRequest(BaseModel):
    """Request memory records"""

    kinds: list[str]


class UpdateGlobalMemoryRequest(BaseModel):
    """update memory record Request"""

    key: int
    kind: str
    value: dict
