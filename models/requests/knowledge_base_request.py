from pydantic import BaseModel
from typing import Optional


class KnowledgeBaseListRequest(BaseModel):
    active: Optional[bool] = None
    path: Optional[list[str]] = None


class KnowledgeBaseUpsertRequest(BaseModel):
    id: Optional[int] = None
    path: list[str]
    link: str
    title: str
    description: Optional[str] = None
    active: bool
