from flask_api import status
from sqlalchemy import desc
from datetime import date, timedelta

from models.main import db
from models.appendix import *
from models.prescription import *
from routes.prescription import getPrescription
from routes.utils import getFeatures
from services import prescription_drug_service

from exception.validation_error import ValidationError

def create_agg_prescription_by_prescription(schema, id_prescription, is_cpoe, out_patient):
    set_schema(schema);

    p = Prescription.query.get(id_prescription)
    if (p is None):
        raise ValidationError('Prescrição inexistente', 'errors.invalidPrescription', status.HTTP_400_BAD_REQUEST)

    if (p.idSegment is None):
        return

    resultPresc, stat = getPrescription(idPrescription=id_prescription)
    p.features = getFeatures(resultPresc)
    p.aggDrugs = p.features['drugIDs']
    p.aggDeps = [p.idDepartment]
    
    if is_cpoe:
        prescription_dates = get_date_range(p)
    else:
        prescription_dates = [p.date]

    for pdate in prescription_dates:
        if out_patient:
            PrescAggID = p.admissionNumber
        else:
            PrescAggID = gen_agg_id(p.admissionNumber, p.idSegment, pdate)

        newPrescAgg = False
        pAgg = Prescription.query.get(PrescAggID)
        if (pAgg is None):
            pAgg = Prescription()
            pAgg.id = PrescAggID
            pAgg.idPatient = p.idPatient
            pAgg.admissionNumber = p.admissionNumber
            pAgg.date = pdate
            pAgg.status = 0
            newPrescAgg = True

        if out_patient:
            pAgg.date = date(pdate.year, pdate.month, pdate.day)

        resultAgg, stat = getPrescription(admissionNumber=p.admissionNumber,\
            aggDate=pAgg.date, idSegment=p.idSegment, is_cpoe=is_cpoe)

        pAgg.idHospital = p.idHospital
        pAgg.idDepartment = p.idDepartment
        pAgg.idSegment = p.idSegment
        pAgg.bed = p.bed
        pAgg.record = p.record
        pAgg.prescriber = 'Prescrição Agregada'
        pAgg.insurance = p.insurance
        pAgg.agg = True

        if p.concilia is None and prescription_drug_service.has_unchecked_drugs(id_prescription):
            pAgg.status = 0

        if 'data' in resultAgg:
            pAgg.features = getFeatures(resultAgg)
            pAgg.aggDrugs = pAgg.features['drugIDs']
            pAgg.aggDeps = list(set([resultAgg['data']['headers'][h]['idDepartment'] for h in resultAgg['data']['headers']]))
            if newPrescAgg: db.session.add(pAgg)

def create_agg_prescription_by_date(schema, admission_number, p_date, is_cpoe):
    set_schema(schema);

    last_prescription = get_last_prescription(admission_number);

    if (last_prescription == None or last_prescription.idSegment == None):
        raise ValidationError('Não foi possível encontrar o segmento desta prescrição', 'errors.invalidSegment', status.HTTP_400_BAD_REQUEST)

    p_id = gen_agg_id(admission_number, last_prescription.idSegment, p_date)

    agg_p = db.session.query(Prescription).get(p_id)

    if (agg_p != None):
        return
    
    agg_p = Prescription()
    agg_p.id = p_id
    agg_p.idPatient = last_prescription.idPatient
    agg_p.admissionNumber = admission_number
    agg_p.date = p_date
    agg_p.status = 0
    agg_p.idHospital = last_prescription.idHospital
    agg_p.idDepartment = last_prescription.idDepartment
    agg_p.idSegment = last_prescription.idSegment
    agg_p.bed = last_prescription.bed
    agg_p.record = last_prescription.record
    agg_p.prescriber = 'Prescrição Agregada'
    agg_p.insurance = last_prescription.insurance
    agg_p.agg = True

    resultAgg, stat = getPrescription(\
        admissionNumber=admission_number,\
        aggDate=agg_p.date, idSegment=agg_p.idSegment, is_cpoe=is_cpoe)

    if 'data' in resultAgg:
        agg_p.features = getFeatures(resultAgg)
        agg_p.aggDrugs = agg_p.features['drugIDs']
        agg_p.aggDeps = list(set([resultAgg['data']['headers'][h]['idDepartment'] for h in resultAgg['data']['headers']]))
    
    db.session.add(agg_p)

def set_schema(schema):
    result = db.engine.execute('SELECT schema_name FROM information_schema.schemata')

    schemaExists = False
    for r in result:
        if r[0] == schema: schemaExists = True

    if not schemaExists:
        raise ValidationError('Schema Inexistente', 'errors.invalidSchema', status.HTTP_400_BAD_REQUEST)

    dbSession.setSchema(schema)


def get_last_prescription(admission_number):
    return db.session.query(Prescription)\
        .filter(Prescription.admissionNumber == admission_number)\
        .filter(Prescription.agg == None)\
        .filter(Prescription.concilia == None)\
        .order_by(desc(Prescription.date))\
        .first()

def gen_agg_id(admission_number, id_segment, pdate):
    id = (pdate.year - 2000) * 100000000000000
    id += pdate.month *          1000000000000
    id += pdate.day *              10000000000
    id += id_segment *              1000000000
    id += admission_number

    return id
    
def get_date_range(p):
    max_date = date.today() + timedelta(days=3)
    start_date = p.date.date() if p.date.date() >= date.today() else date.today()
    end_date = (p.expire.date() if p.expire != None else p.date.date()) + timedelta(days=1) 
    end_date = end_date if end_date < max_date else max_date
    return [start_date + timedelta(days=x) for x in range((end_date-start_date).days)]