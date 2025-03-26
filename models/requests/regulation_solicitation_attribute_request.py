"""Request model for regulation solicitation attribute"""

from pydantic import BaseModel


class RegulationSolicitationAttributeRequest(BaseModel):
    """Request model for regulation solicitation attribute (create request)"""

    idRegSolicitation: int
    tpAttribute: int
    tpStatus: int
    value: dict


class RegSolicitationAttributeListRequest(BaseModel):
    """Request model to list solicitation attributes"""

    idRegSolicitation: int
    tpAttribute: int
