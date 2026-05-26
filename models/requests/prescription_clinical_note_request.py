from typing import Optional

from pydantic import BaseModel


class PrescriptionClinicalNoteUpsertRequest(BaseModel):
    id: Optional[int] = None
    idPrescription: int
    idClinicalNoteType: Optional[str] = None
    concilia: Optional[str] = None
    tpStatus: int = 0
    errorDescription: Optional[str] = None
    text: Optional[str] = None
