from utils import status
from sqlalchemy import desc, text, select, func, and_
from flask_sqlalchemy.session import Session
from datetime import date, timedelta

from models.main import db
from models.appendix import *
from models.prescription import *
from models.enums import PrescriptionDrugAuditTypeEnum, DrugTypeEnum
from routes.prescription import getPrescription
from routes.utils import getFeatures, gen_agg_id
from services import prescription_service, prescription_drug_service

from exception.validation_error import ValidationError


def create_agg_prescription_by_prescription(
    schema, id_prescription, is_cpoe, out_patient, is_pmc=False, force=False
):
    set_schema(schema)

    p = Prescription.query.get(id_prescription)
    if p is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidPrescription",
            status.HTTP_400_BAD_REQUEST,
        )

    if p.idSegment is None:
        return

    if not force and not _has_new_itens(id_prescription):
        return

    resultPresc, stat = getPrescription(idPrescription=id_prescription)
    p.features = getFeatures(resultPresc)
    p.aggDrugs = p.features["drugIDs"]
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
        if pAgg is None:
            pAgg = Prescription()
            pAgg.id = PrescAggID
            pAgg.idPatient = p.idPatient
            pAgg.admissionNumber = p.admissionNumber
            pAgg.date = pdate
            pAgg.status = 0
            newPrescAgg = True

        if out_patient:
            pAgg.date = date(pdate.year, pdate.month, pdate.day)

        resultAgg, stat = getPrescription(
            admissionNumber=p.admissionNumber,
            aggDate=pAgg.date,
            idSegment=p.idSegment,
            is_cpoe=is_cpoe,
            is_pmc=is_pmc,
        )

        pAgg.idHospital = p.idHospital
        pAgg.idDepartment = p.idDepartment
        pAgg.idSegment = p.idSegment
        pAgg.bed = p.bed
        pAgg.record = p.record
        pAgg.prescriber = "Prescrição Agregada"
        pAgg.insurance = p.insurance
        pAgg.agg = True
        pAgg.update = datetime.today()

        if p.concilia is None and pAgg.status == "s":
            prescalc_user = User()
            prescalc_user.id = 0

            drug_count = prescription_drug_service.count_drugs_by_prescription(
                prescription=p,
                drug_types=[
                    DrugTypeEnum.DRUG.value,
                    DrugTypeEnum.PROCEDURE.value,
                    DrugTypeEnum.SOLUTION.value,
                ],
                user=prescalc_user,
            )

            if drug_count > 0:
                pAgg.status = 0

                prescription_service.audit_check(
                    prescription=pAgg, user=prescalc_user, extra={"prescalc": True}
                )

        if "data" in resultAgg:
            pAgg.features = getFeatures(resultAgg)
            pAgg.aggDrugs = pAgg.features["drugIDs"]
            pAgg.aggDeps = list(
                set(
                    [
                        resultAgg["data"]["headers"][h]["idDepartment"]
                        for h in resultAgg["data"]["headers"]
                    ]
                )
            )
            if newPrescAgg:
                db.session.add(pAgg)

    _log_processed_date(id_prescription_array=[id_prescription], schema=schema)


def create_agg_prescription_by_date(schema, admission_number, p_date, is_cpoe):
    create_new = False
    set_schema(schema)

    last_prescription = get_last_prescription(admission_number)

    if last_prescription == None or last_prescription.idSegment == None:
        raise ValidationError(
            "Não foi possível encontrar o segmento deste atendimento",
            "errors.invalidSegment",
            status.HTTP_400_BAD_REQUEST,
        )

    p_id = gen_agg_id(admission_number, last_prescription.idSegment, p_date)

    agg_p = db.session.query(Prescription).get(p_id)

    if agg_p is None:
        create_new = True

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
        agg_p.prescriber = "Prescrição Agregada"
        agg_p.insurance = last_prescription.insurance
        agg_p.agg = True
        agg_p.update = datetime.today()

    resultAgg, stat = getPrescription(
        admissionNumber=admission_number,
        aggDate=agg_p.date,
        idSegment=agg_p.idSegment,
        is_cpoe=is_cpoe,
    )

    if "data" in resultAgg:
        agg_p.update = datetime.today()
        agg_p.features = getFeatures(resultAgg)
        agg_p.aggDrugs = agg_p.features["drugIDs"]
        agg_p.aggDeps = list(
            set(
                [
                    resultAgg["data"]["headers"][h]["idDepartment"]
                    for h in resultAgg["data"]["headers"]
                ]
            )
        )

        internal_prescription_ids = []
        for h in resultAgg["data"]["headers"]:
            internal_prescription_ids.append(h)

        _log_processed_date(
            id_prescription_array=internal_prescription_ids, schema=schema
        )

    if create_new:
        db.session.add(agg_p)


def _log_processed_date(id_prescription_array, schema):
    query = text(
        f"""
        insert into {schema}.presmed_audit (
            tp_audit, fkpresmed, created_at, created_by
        )
        select
            :auditType,
            fkpresmed,
            :createdAt,
            0
        from
            {schema}.presmed
        where
            fkprescricao = any(:prescriptionArray)
    """
    )

    db.session.execute(
        query,
        {
            "auditType": PrescriptionDrugAuditTypeEnum.PROCESSED.value,
            "prescriptionArray": id_prescription_array,
            "createdAt": datetime.today(),
        },
    )


def set_schema(schema):
    db_session = Session(db)
    result = db_session.execute(
        text("SELECT schema_name FROM information_schema.schemata")
    )

    schemaExists = False
    for r in result:
        if r[0] == schema:
            schemaExists = True

    if not schemaExists:
        raise ValidationError(
            "Schema Inexistente", "errors.invalidSchema", status.HTTP_400_BAD_REQUEST
        )

    db_session.close()

    dbSession.setSchema(schema)


def get_last_prescription(admission_number):
    return (
        db.session.query(Prescription)
        .filter(Prescription.admissionNumber == admission_number)
        .filter(Prescription.agg == None)
        .filter(Prescription.concilia == None)
        .filter(Prescription.idSegment != None)
        .order_by(desc(Prescription.date))
        .first()
    )


def get_last_agg_prescription(admission_number) -> Prescription:
    return (
        db.session.query(Prescription)
        .filter(Prescription.admissionNumber == admission_number)
        .filter(Prescription.agg == True)
        .filter(Prescription.concilia == None)
        .filter(Prescription.idSegment != None)
        .order_by(desc(Prescription.date))
        .first()
    )


def get_date_range(p):
    max_date = date.today() + timedelta(days=3)
    start_date = p.date.date() if p.date.date() >= date.today() else date.today()
    end_date = (p.expire.date() if p.expire != None else p.date.date()) + timedelta(
        days=1
    )
    end_date = end_date if end_date < max_date else max_date
    return [start_date + timedelta(days=x) for x in range((end_date - start_date).days)]


def _has_new_itens(id_prescription: int):
    query = (
        select(PrescriptionDrug.id, func.count(PrescriptionDrugAudit.id))
        .select_from(PrescriptionDrug)
        .outerjoin(
            PrescriptionDrugAudit,
            and_(
                PrescriptionDrug.id == PrescriptionDrugAudit.idPrescriptionDrug,
                PrescriptionDrugAudit.auditType
                == PrescriptionDrugAuditTypeEnum.PROCESSED.value,
            ),
        )
        .where(PrescriptionDrug.idPrescription == id_prescription)
        .group_by(PrescriptionDrug.id)
        .having(func.count(PrescriptionDrugAudit.id) == 0)
    )

    results = db.session.execute(query).all()

    if len(results) > 0:
        return True

    return False
