"""Request models for the allergy records (alergia)"""

from pydantic import BaseModel


class AllergySubstanceRequest(BaseModel):
    """The substance of the allergy records of a drug name without a medicamento
    record: every record with the same fkmedicamento and nome_medicamento.
    Without sctid the substance is removed"""

    idDrug: int | None = None
    drugName: str | None = None
    sctid: int | None = None
