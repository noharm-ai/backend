from pydantic import BaseModel
from typing import Optional


class KnowledgeBaseListRequest(BaseModel):
    active: Optional[bool] = None
    path: Optional[list[str]] = None


class KnowledgeBaseSearchRequest(BaseModel):
    query: Optional[str] = None
