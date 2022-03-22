from models.main import db
from sqlalchemy import asc

from models.appendix import *
from models.prescription import *


def get_patients():
    return db.session\
        .query(Patient)\
        .order_by(asc(Patient.admissionDate))\
        .limit(500)\
        .all()