from sqlalchemy import desc
from datetime import date

from models.main import db
from models.appendix import *
from models.prescription import *

def search(search_key):
    return db.session\
        .query(
            Prescription, Patient.birthdate.label('birthdate'), Patient.gender.label('gender'),\
            Department.name.label('department')
        )\
        .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)\
        .outerjoin(\
            Department, and_(\
                Department.id == Prescription.idDepartment, Department.idHospital == Prescription.idHospital\
            )\
        )\
        .filter(or_(
            Prescription.id == search_key,
            and_(
                Prescription.admissionNumber == search_key,
                func.date(Prescription.date) <= date.today(),
                Prescription.agg != None
            )
        ))\
        .order_by(desc(Prescription.date))\
        .limit(5)\
        .all()