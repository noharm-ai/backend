from pydantic import BaseModel
from typing import Optional


class TagListRequest(BaseModel):
    active: Optional[bool] = None
    tagType: Optional[str] = None


class TagUpsertRequest(BaseModel):
    tag: str
    tagType: str
    active: bool
