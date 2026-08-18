"""Request models for admin report operations"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class UpdateReportGraphsRequest(BaseModel):
    """Request model for updating report graphs"""

    graphs: Optional[Any] = Field(None, description="Graph configurations as JSON")
