"""Request model: admin global exam"""

from typing import Optional

from pydantic import BaseModel


class GlobalExamListRequest(BaseModel):
    """Global exam list request parameters"""

    active: Optional[bool] = None
    term: Optional[str] = None


class GlobalExamUpsertRequest(BaseModel):
    """Global exam create/update request params"""

    tp_exam: str = None
    name: str
    initials: str
    measureunit: str
    active: bool
    min_adult: float
    max_adult: float
    ref_adult: str
    min_pediatric: float
    max_pediatric: float
    ref_pediatric: str
