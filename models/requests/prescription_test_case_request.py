"""Request models: prescription test cases, created by maintainers"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# the item kinds the prescription view groups by (presmed.origem after the trigger)
PrescriptionTestCaseItemSource = Literal[
    "Medicamentos", "Soluções", "Proced/Exames", "Dietas", "Materiais"
]


class PrescriptionTestCasePatientRequest(BaseModel):
    """The patient of a new admission"""

    birthdate: Optional[date] = None
    gender: Optional[Literal["M", "F"]] = None
    weight: Optional[float] = Field(default=None, gt=0)
    height: Optional[float] = Field(default=None, gt=0)


class PrescriptionTestCaseItemRequest(BaseModel):
    """An item of the prescription, as the hospital sends it"""

    idDrug: int
    source: PrescriptionTestCaseItemSource = "Medicamentos"
    dose: Optional[float] = Field(default=None, ge=0)
    measureUnit: Optional[str] = None
    frequency: Optional[str] = None
    interval: Optional[str] = Field(default=None, max_length=50)
    route: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=2000)


class PrescriptionTestCaseRequest(BaseModel):
    """A test case prescription: for a new admission (patient) or an existing one"""

    # existing admission; without it a new admission is created from patient
    admissionNumber: Optional[int] = None
    patient: Optional[PrescriptionTestCasePatientRequest] = None
    idDepartment: int
    # only needed when the department is in more than one hospital
    idHospital: Optional[int] = None
    # defaults to now
    date: Optional[datetime] = None
    # defaults to a day after date
    expire: Optional[datetime] = None
    bed: Optional[str] = Field(default=None, max_length=16)
    prescriber: Optional[str] = Field(default=None, max_length=255)
    items: list[PrescriptionTestCaseItemRequest] = Field(min_length=1, max_length=100)
