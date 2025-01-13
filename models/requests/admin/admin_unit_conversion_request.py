from pydantic import BaseModel


class SetFactorRequest(BaseModel):
    idDrug: int
    idSegment: int
    factor: float
