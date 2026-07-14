from typing import Literal, Optional

from pydantic import BaseModel, Field


class SuggestGraphsColumn(BaseModel):
    key: str
    label: str
    type: Literal["string", "number", "date", "boolean", "object"]
    options: Optional[list[str]] = None
    distinctCount: Optional[int] = None


class SuggestGraphsRequest(BaseModel):
    """Request model for LLM-based chart suggestions on custom reports."""

    columns: list[SuggestGraphsColumn] = Field(..., min_length=1, max_length=200)
    sampleRows: list[dict] = Field(..., min_length=1, max_length=10)
    hint: Optional[str] = Field(None, max_length=500)
    existingTitles: list[str] = Field(default_factory=list, max_length=100)
