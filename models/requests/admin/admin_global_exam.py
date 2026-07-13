"""Request model: admin global exam"""

from pydantic import BaseModel


class SegmentExamGetRequest(BaseModel):
    """Request parameters to fetch a single segment exam"""

    idSegment: int
    examType: str
