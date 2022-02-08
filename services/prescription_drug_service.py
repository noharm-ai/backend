from models.main import db

from models.appendix import *
from models.prescription import *

def get(idPrescriptionDrug):
    return db.session\
        .query(PrescriptionDrug, Drug, MeasureUnit, Frequency, '0',\
                func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4).label('score'),
                DrugAttributes, Notes.notes, Prescription.status, Prescription.expire)\
        .outerjoin(Outlier, Outlier.id == PrescriptionDrug.idOutlier)\
        .outerjoin(Drug, Drug.id == PrescriptionDrug.idDrug)\
        .outerjoin(Notes, Notes.idPrescriptionDrug == PrescriptionDrug.id)\
        .outerjoin(Prescription, Prescription.id == PrescriptionDrug.idPrescription)\
        .outerjoin(MeasureUnit, and_(MeasureUnit.id == PrescriptionDrug.idMeasureUnit, MeasureUnit.idHospital == Prescription.idHospital))\
        .outerjoin(Frequency, and_(Frequency.id == PrescriptionDrug.idFrequency, Frequency.idHospital == Prescription.idHospital))\
        .outerjoin(DrugAttributes, and_(DrugAttributes.idDrug == PrescriptionDrug.idDrug, DrugAttributes.idSegment == PrescriptionDrug.idSegment))\
        .filter(PrescriptionDrug.id == idPrescriptionDrug)\
        .first()