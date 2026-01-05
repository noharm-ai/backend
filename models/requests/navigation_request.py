from pydantic import BaseModel


class NavCopyPatientRequest(BaseModel):
    admission_number: int
    name: str
    phone: str
    clinical_notes: dict
