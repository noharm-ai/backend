from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PatientListRequest(BaseModel):
    """Request model for listing patients (primary care)."""

    idSegment: Optional[int] = None
    idDepartmentList: Optional[list[int]] = None
    nextAppointmentStartDate: Optional[datetime] = None
    nextAppointmentEndDate: Optional[datetime] = None
    appointment: Optional[str] = None
    scheduledByList: Optional[list[int]] = None
    attendedByList: Optional[list[int]] = None
    dischargeDateStart: Optional[datetime] = None
    dischargeDateEnd: Optional[datetime] = None
