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
    idList: Optional[list[int]] = None
    typeList: Optional[list[str]] = None
    stageList: Optional[list[int]] = None
    idPatientList: Optional[list[int]] = None
    idIcdList: Optional[list[str]] = None
    idIcdGroupList: Optional[list[str]] = None
    limit: int
    offset: int
    order: list[Order]
