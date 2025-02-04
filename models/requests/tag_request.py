from pydantic import BaseModel, Field
from typing import Optional


class TagListRequest(BaseModel):
    active: Optional[bool] = None
    tagType: Optional[str] = None


class TagUpsertRequest(BaseModel):
    name: str = Field(min_length=3, max_length=40)
    tagType: int
    active: bool
    new: bool = False
