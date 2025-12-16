"""Request models for admin report operations"""

from typing import Optional

from pydantic import BaseModel, Field


class UpsertReportRequest(BaseModel):
    """Request model for creating a new report"""

    id: Optional[int] = Field(None, description="Report identifier")
    name: str = Field(..., min_length=1, max_length=150, description="Report name")
    description: str = Field(
        ..., min_length=1, max_length=250, description="Report description"
    )
    sql: str = Field(..., min_length=1, description="SQL query for the report")
    active: bool = Field(default=True, description="Whether the report is active")
