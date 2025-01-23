from pydantic import BaseModel
from typing import Optional


class AdminSubstanceRequest(BaseModel):
    id: Optional[int] = None
    name: str
    idClass: Optional[str] = None
    active: bool
    link: Optional[str] = None
    handling: Optional[dict] = None
    adminText: Optional[str] = None
    maxdoseAdult: Optional[float] = None
    maxdoseAdultWeight: Optional[float] = None
    maxdosePediatric: Optional[float] = None
    maxdosePediatricWeight: Optional[float] = None
    defaultMeasureUnit: Optional[str] = None
    tags: Optional[list[str]] = None
    divisionRange: Optional[float] = None
    kidneyAdult: Optional[float] = None
    kidneyPediatric: Optional[float] = None
    liverAdult: Optional[float] = None
    liverPediatric: Optional[float] = None
    platelets: Optional[int] = None
    fallRisk: Optional[int] = None
    lactating: Optional[str] = None
    pregnant: Optional[str] = None
