from typing import Optional

from pydantic import BaseModel


class PrescriptionClinicalNoteUpsertRequest(BaseModel):
    id: Optional[int] = None
    idPrescription: int
    idTipoEvolucao: Optional[str] = None
    concilia: Optional[str] = None
    tpStatus: int = 0
    descErroIntegracao: Optional[str] = None
    texto: Optional[str] = None
