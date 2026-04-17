from typing import Optional

from pydantic import BaseModel, Field


class TagListRequest(BaseModel):
    active: Optional[bool] = None
    tagType: Optional[str] = None


class TagUpsertRequest(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    tagType: int
    active: bool
    new: bool = False
