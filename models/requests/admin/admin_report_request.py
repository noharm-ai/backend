"""Request models for admin report operations"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class UpdateReportGraphsRequest(BaseModel):
    """Request model for updating report graphs"""

    graphs: Optional[Any] = Field(None, description="Graph configurations as JSON")


class CopySourceListRequest(BaseModel):
    """Request model for listing the reports usable as a chart copy source.

    The field is named sourceSchema rather than schema to stay clear of
    BaseModel.schema. The pattern is defense in depth only: the schema is
    authorized against public.schema_config before it reaches a query.
    """

    sourceSchema: Optional[str] = Field(
        None,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Schema to read the copy sources from. Defaults to the user's own",
    )


class CopySourceGraphsRequest(CopySourceListRequest):
    """Request model for reading the charts of a copy-source report"""

    idReport: int = Field(description="Report to copy the charts from")
