from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class Order(BaseModel):
    field: str
    direction: str


class RegulationPrioritizationRequest(BaseModel):
    startDate: datetime
    endDate: Optional[datetime] = None
    scheduleStartDate: Optional[datetime] = None
    scheduleEndDate: Optional[datetime] = None
    transportationStartDate: Optional[datetime] = None
    transportationEndDate: Optional[datetime] = None
    idDepartmentList: Optional[list[int]] = None
    typeType: Optional[int] = None
    riskList: Optional[list[int]] = None
    typeList: Optional[list[str]] = []
    stageList: Optional[list[int]] = []
    limit: int
    offset: int
    order: list[Order]
