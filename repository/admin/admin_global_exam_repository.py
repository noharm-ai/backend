"""Repository: admin global exam operations"""

from sqlalchemy import func, or_

from models.appendix import GlobalExam
from models.main import db
from models.requests.admin.admin_global_exam import GlobalExamListRequest


def list_global_exams(request_data: GlobalExamListRequest) -> list[GlobalExam]:
    """List global exams"""
    query = db.session.query(GlobalExam)

    if request_data.active is not None:
        query = query.filter(GlobalExam.active == request_data.active)

    if request_data.term:
        term = f"%{request_data.term}%"
        query = query.filter(
            or_(
                func.lower(GlobalExam.name).like(func.lower(term)),
                func.lower(GlobalExam.initials).like(func.lower(term)),
                func.lower(GlobalExam.tp_exam).like(func.lower(term)),
            )
        )

    return query.order_by(GlobalExam.name).all()


def get_global_exam_by_id(tp_exam: str) -> GlobalExam:
    """Get global exam by id"""
    return db.session.query(GlobalExam).filter(GlobalExam.tp_exam == tp_exam).first()
