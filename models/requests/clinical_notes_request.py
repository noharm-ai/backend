from typing import Optional

from pydantic import BaseModel


class GenerateSoapRequest(BaseModel):
    """Request model for LLM-based SOAP evolution generation from a clinical note"""

    id: int
    prompt_key: Optional[str] = None


class ClinicalNoteSignRequest(BaseModel):
    """Request model for requesting a digital signature of a clinical note"""

    id: int
    signer_name: str
    signer_email: str
    # debugging aid: return the generated PDF (base64) without contacting ODOO
    preview: Optional[bool] = False
