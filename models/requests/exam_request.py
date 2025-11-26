"""Request model: exams"""

from datetime import datetime
from pydantic import BaseModel


class ExamCreateRequest(BaseModel):
    """Exam create request model"""

    admissionNumber: int
    examDate: datetime
    examType: str
    result: float


class ExamCreateItemRequest(BaseModel):
    """Exam create item request model"""

    examDate: datetime
    examType: str
    result: float


class ExamCreateMultipleRequest(BaseModel):
    """Exam create multiple request model"""

    admissionNumber: int
    exams: list[ExamCreateItemRequest]


class ExamDeleteRequest(BaseModel):
    """Exam delete request model"""

    admissionNumber: int
    idExam: int
