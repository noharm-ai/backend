"""Request model: exams"""

from datetime import datetime
from pydantic import BaseModel


class ExamCreateRequest(BaseModel):
    """Exam create request model"""

    admissionNumber: int
    examDate: datetime
    examType: str
    result: float
