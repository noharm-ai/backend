from pydantic import BaseModel, Field
from typing import Optional


class KnowledgeBaseListRequest(BaseModel):
    active: Optional[bool] = None
    path: Optional[list[str]] = None


class KnowledgeBaseSearchRequest(BaseModel):
    query: Optional[str] = None


class KnowledgeBaseElementListRequest(BaseModel):
    page: str = Field(min_length=1, max_length=255)


class KnowledgeBaseElementSaveRequest(BaseModel):
    page: str = Field(min_length=1, max_length=255)
    selector: str = Field(min_length=1, max_length=1000)
    label: Optional[str] = Field(default=None, max_length=255)
    # the element's complete article set: an empty list unpins the element
    articleIds: list[int] = Field(default_factory=list, max_length=20)
