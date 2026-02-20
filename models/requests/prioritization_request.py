from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class PrioritizationRequest(BaseModel):
    idSegment: Optional[int] = None
    idSegmentList: list[int] = Field(default_factory=list)
    idDept: list[int] = Field(default_factory=list)
    idDrug: list[int] = Field(default_factory=list)
    startDate: date = Field(default_factory=date.today)
    endDate: Optional[date] = None
    pending: bool = False
    agg: bool = False
    currentDepartment: bool = False
    concilia: bool = False
    allDrugs: bool = False
    insurance: Optional[str] = None
    indicators: list[str] = Field(default_factory=list)
    frequencies: list[str] = Field(default_factory=list)
    patientStatus: Optional[str] = None
    substances: list[int] = Field(default_factory=list)
    substanceClasses: list[str] = Field(default_factory=list)
    patientReviewType: Optional[int] = None
    drugAttributes: list[str] = Field(default_factory=list)
    idPatient: list[int] = Field(default_factory=list)
    intervals: list[str] = Field(default_factory=list)
    prescriber: Optional[str] = None
    diff: Optional[bool] = None
    global_score_min: Optional[int] = None
    global_score_max: Optional[int] = None
    pending_interventions: Optional[bool] = None
    has_conciliation: Optional[bool] = None
    alert_level: Optional[str] = None
    tags: Optional[list[str]] = None
    has_clinical_notes: Optional[bool] = None
    protocols: Optional[list[int]] = None
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    id_patient_by_name_list: Optional[list[int]] = None
    id_icd_list: Optional[list[str]] = None
    id_icd_group_list: Optional[list[str]] = None
    city: Optional[str] = None
    medical_record: Optional[str] = None
    bed: Optional[str] = None
    bed_list: Optional[list[str]] = None
    specialty_list: Optional[list[str]] = None
