"""Request models for regulation reports"""

from typing import Optional

from pydantic import BaseModel


class Order(BaseModel):
    field: str
    direction: str


class RegIndicatorsPanelReportRequest(BaseModel):
    """Request model for regulation indicators panel report"""

    indicator: str
    name: Optional[str] = None
    cpf: Optional[str] = None
    cns: Optional[str] = None
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    gender: Optional[str] = None
    health_unit: Optional[str] = None
    health_team: Optional[str] = None
    health_agent: Optional[str] = None
    has_indicator: Optional[bool] = None
    limit: int
    offset: int
    order: list[Order]
