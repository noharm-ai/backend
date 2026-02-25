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
    weekdays_only: Optional[bool] = None


class PrescriptionReportRequest(BaseModel):
    year: int
    id_department: Optional[list[int]] = None
    segment: Optional[list[str]] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    global_score_start: Optional[int] = None
    global_score_end: Optional[int] = None
    weekdays_only: Optional[bool] = None
    consider_empty_prescriptions: bool = False
    remove_prescription_at_discharge_date: Optional[str] = None
