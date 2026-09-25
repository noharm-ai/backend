"""Request models: knowledge base articles"""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class KnowledgeBaseListRequest(BaseModel):
    """Filters for the knowledge base panel (help articles of a screen)"""

    active: Optional[bool] = None
    path: Optional[list[str]] = None
    section: Optional[list[str]] = None


class KnowledgeBaseManageListRequest(BaseModel):
    """Filters for the knowledge base maintenance screen"""

    active: Optional[bool] = None
    path: Optional[list[str]] = None
    section: Optional[list[str]] = None
    term: Optional[str] = None


class KnowledgeBaseUpsertRequest(BaseModel):
    """Create (no id) or update (id) a knowledge base article"""

    id: Optional[int] = None
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    path: list[str] = []
    section: list[str] = []
    link: Optional[str] = Field(default=None, max_length=255)
    content: Optional[str] = None
    active: bool = True

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        """Surrounding whitespace is not part of the title"""
        return value.strip()

    @field_validator("content")
    @classmethod
    def empty_html_as_none(cls, value: Optional[str]) -> Optional[str]:
        """An editor left empty still sends markup (<p></p>): that is no content"""
        if value is None or not re.sub(r"<[^>]*>|&nbsp;", "", value).strip():
            return None

        return value

    @field_validator("description", "link", "content")
    @classmethod
    def blank_as_none(cls, value: Optional[str]) -> Optional[str]:
        """Empty strings are stored as null"""
        if value is None or not value.strip():
            return None

        return value.strip()

    @field_validator("path", "section")
    @classmethod
    def clean_keys(cls, value: list[str]) -> list[str]:
        """Drop blanks and duplicates, keeping the given order"""
        cleaned = []
        for item in value:
            item = item.strip()
            if item and item not in cleaned:
                cleaned.append(item)

        return cleaned
