from models.main import db
from sqlalchemy import asc, distinct

from models.appendix import *
from models.prescription import *

# MEASURE UNIT
def getPreviouslyPrescribedUnits(idDrug, idSegment):
    u = db.aliased(MeasureUnit)
    agg = db.aliased(PrescriptionAgg)

    return db.session\
        .query(u.id, u.description, func.sum(func.coalesce(agg.countNum, 0)).label('count'))\
        .select_from(u)\
        .outerjoin(agg, and_(agg.idMeasureUnit == u.id, agg.idDrug == idDrug, agg.idSegment == idSegment))\
        .filter(agg.idSegment == idSegment)\
        .group_by(u.id, u.description, agg.idMeasureUnit)\
        .order_by(asc(u.description))\
        .all()

def getUnits(idHospital):
    return db.session.query(MeasureUnit)\
        .filter(MeasureUnit.idHospital == idHospital)\
        .order_by(asc(MeasureUnit.description))\
        .all()

# FREQUENCY
def getPreviouslyPrescribedFrequencies(idDrug, idSegment):
    agg = db.aliased(PrescriptionAgg)
    f = db.aliased(Frequency)

    return db.session\
        .query(f.id, f.description, func.sum(func.coalesce(agg.countNum, 0)).label('count'))\
        .select_from(f)\
        .outerjoin(agg, and_(agg.idFrequency == f.id, agg.idDrug == idDrug, agg.idSegment == idSegment))\
        .filter(agg.idSegment == idSegment)\
        .group_by(f.id, f.description, agg.idFrequency)\
        .order_by(asc(f.description))\
        .all()

def getFrequencies(idHospital):
    return db.session.query(Frequency)\
        .filter(Frequency.idHospital == idHospital)\
        .order_by(asc(Frequency.description))\
        .all()


def get_all_frequencies():
    return db.session.query(distinct(Frequency.id), Frequency.description)\
        .select_from(Frequency)\
        .order_by(asc(Frequency.description))\
        .all()