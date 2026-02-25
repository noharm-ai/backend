"""Repository: prescription drug related operations"""

from models.main import db, User
from models.prescription import CheckedIndex


def get_drug_check_history(admission_number: int, id_drug: int):
    """Get check history for a drug in a given admission from checkedindex table"""
    return (
        db.session.query(CheckedIndex, User)
        .outerjoin(User, CheckedIndex.createdBy == User.id)
        .filter(CheckedIndex.admissionNumber == admission_number)
        .filter(CheckedIndex.idDrug == id_drug)
        .order_by(CheckedIndex.createdAt.desc())
        .all()
    )
