"""Repository for prescalc operations"""

from typing import Union

from sqlalchemy import desc

from models.main import db
from models.prescription import Prescription
from models.segment import Segment


def get_last_prescription(
    admission_number: int, cpoe: Union[bool, None], agg: bool
) -> Union[Prescription, None]:
    """
    Search for the last prescription for a given admission number.
    Do not consider concilia prescriptions.

    Args:
        admission_number (int): The admission number to search for.
        cpoe (bool): Whether to filter by cpoe.
        agg (bool): Whether to filter by aggregated prescription.

    Returns:
        Prescription: The last prescription for the given admission number.
    """

    query = (
        db.session.query(Prescription)
        .outerjoin(Segment, Prescription.idSegment == Segment.id)
        .filter(Prescription.admissionNumber == admission_number)
        .filter(Prescription.concilia == None)
        .filter(Prescription.idSegment != None)
    )

    if agg:
        query = query.filter(Prescription.agg == True)
    else:
        query = query.filter(Prescription.agg == None)

    if cpoe is not None:
        query = query.filter(Segment.cpoe == cpoe)

    return query.order_by(desc(Prescription.date)).first()
