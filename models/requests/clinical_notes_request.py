from typing import Optional

from pydantic import BaseModel


class GenerateSoapRequest(BaseModel):
    """Request model for LLM-based SOAP evolution generation from a clinical note"""

    id: int
    prompt_key: Optional[str] = None
