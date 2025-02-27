"""Request model for regulation solicitation"""

from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel


class RegulationSolicitationRequest(BaseModel):
    """Request model for regulation solicitation (create request)"""

    idPatient: int
    birthdate: Optional[date]
    idDepartment: int
    solicitationDate: datetime
    idRegSolicitationType: int
    risk: int
    cid: Optional[str]
    attendant: Optional[str]
    attendantRecord: Optional[str]
    justification: Optional[str]
