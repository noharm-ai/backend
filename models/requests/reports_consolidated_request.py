from datetime import date
from typing import Optional

from pydantic import BaseModel


class PatientDayReportRequest(BaseModel):
    year: int
    id_department: Optional[list[int]] = None
    segment: Optional[list[str]] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    global_score_start: Optional[int] = None
    global_score_end: Optional[int] = None
