"""Request models for the drug interaction trace"""

from pydantic import BaseModel


class InteractionTraceRequest(BaseModel):
    """Interaction trace request parameters.

    Without idPrescriptionDrugFrom only the items that can be traced are
    returned. With it, exactly one of idPrescriptionDrugTo (another prescribed
    item) or sctidAllergy (a substance the patient is allergic to) is required.
    """

    idPrescription: int
    idPrescriptionDrugFrom: int | None = None
    idPrescriptionDrugTo: int | None = None
    sctidAllergy: int | None = None
