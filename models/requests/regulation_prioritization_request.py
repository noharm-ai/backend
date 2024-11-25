from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class Order(BaseModel):
    field: str
    direction: str


class RegulationPrioritizationRequest(BaseModel):
    startDate: datetime
    endDate: Optional[datetime] = None
    typeList: Optional[list[str]] = []
    stageList: Optional[list[int]] = []
    limit: int
    offset: int
    order: list[Order]
