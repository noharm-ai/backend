from sqlalchemy import desc, text, select, func, and_
from flask_sqlalchemy.session import Session
from datetime import date, datetime, timedelta

from models.main import db, User, dbSession
from models.prescription import (
    Prescription,
    PrescriptionDrug,
    PrescriptionDrugAudit,
    Patient,
    PrescriptionAudit,
)
from models.enums import (
    PrescriptionAuditTypeEnum,
    PrescriptionDrugAuditTypeEnum,
    DrugTypeEnum,
    PatientConciliationStatusEnum,
    FeatureEnum,
)
from models.appendix import SchemaConfig
from services import (
    prescription_drug_service,
    prescription_check_service,
    prescription_view_service,
    feature_service,
)
from exception.validation_error import ValidationError
from decorators.has_permission_decorator import has_permission, Permission
from utils import status, prescriptionutils


@has_permission(Permission.READ_STATIC)
def create_agg_prescription_by_prescription(
    schema, id_prescription, out_patient, user_context: User, force=False
):
    _set_schema(schema)

    if feature_service.is_cpoe():
        raise ValidationError(
            "CPOE deve acionar o fluxo por atendimento",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    p = (
        db.session.query(Prescription)
        .filter(Prescription.id == id_prescription)
        .first()
    )
    if p is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidPrescription",
            status.HTTP_400_BAD_REQUEST,
        )

    if p.idSegment is None:
        return

    processed_status = _get_processed_status(id_prescription=id_prescription)

    if not force and processed_status == "PROCESSED":
        return

    _update_patient_conciliation_status(prescription=p)

    prescription_data = prescription_view_service.static_get_prescription(
        id_prescription=id_prescription, user_context=user_context
    )
    p.features = prescriptionutils.getFeatures(prescription_data)
    p.aggDrugs = p.features["drugIDs"]
    p.aggDeps = [p.idDepartment]

    if p.concilia != None:
        db.session.flush()

        return

    pdate = p.date

    if processed_status == "NEW_ITENS":
        days_between = (datetime.today().date() - p.date.date()).days
        if days_between <= 1:
            # updates on last day prescriptions should affect current agg prescription
            pdate = datetime.today().date()

    if out_patient:
        PrescAggID = p.admissionNumber
    else:
        PrescAggID = prescriptionutils.gen_agg_id(p.admissionNumber, p.idSegment, pdate)

    is_new_prescription = False
    pAgg = Prescription.query.get(PrescAggID)
    if pAgg is None:
        pAgg = Prescription()
        pAgg.id = PrescAggID
        pAgg.idPatient = p.idPatient
        pAgg.admissionNumber = p.admissionNumber
        pAgg.date = pdate
        pAgg.status = 0
        db.session.add(pAgg)
        is_new_prescription = True

    if out_patient:
        pAgg.date = date(pdate.year, pdate.month, pdate.day)

    pAgg.idHospital = p.idHospital
    pAgg.idDepartment = p.idDepartment
    pAgg.idSegment = p.idSegment
    pAgg.bed = p.bed
    pAgg.record = p.record
    pAgg.prescriber = "Prescrição Agregada"
    pAgg.insurance = p.insurance
    pAgg.agg = True
    pAgg.update = datetime.today()
    db.session.flush()

    if is_new_prescription:
        _audit_create(prescription=pAgg)

    agg_data = prescription_view_service.static_get_prescription(
        id_prescription=pAgg.id, user_context=user_context
    )

    features = prescriptionutils.getFeatures(
        result=agg_data, agg_date=pAgg.date, intervals_for_agg_date=True
    )
    score_variation = _get_score_variation(prescription=pAgg, features=features)
    features.update({"scoreVariation": score_variation})

    pAgg.features = features
    pAgg.aggDrugs = pAgg.features["drugIDs"]
    pAgg.aggDeps = pAgg.features["departmentList"]

    if p.concilia is None and (pAgg.status == "s" or p.status == "s"):
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
            if pAgg.status == "s":
                remove_agg_check = True

                # if it was checked before this process, keep it
                if p.status == "s" and processed_status == "NEW_PRESCRIPTION":
                    remove_agg_check = False

                if remove_agg_check:
                    pAgg.status = 0

                    prescription_check_service.audit_check(
                        prescription=pAgg, user=prescalc_user, extra={"prescalc": True}
                    )

            # if it was checked before this process, keep it
            if p.status == "s" and processed_status == "NEW_ITENS":
                p.update = datetime.today()
                p.user = None
                p.status = 0

                prescription_check_service.audit_check(
                    prescription=p, user=prescalc_user, extra={"prescalc": True}
                )

    _log_processed_date(id_prescription_array=[id_prescription], schema=schema)


@has_permission(Permission.READ_STATIC)
def create_agg_prescription_by_date(
    schema, admission_number, p_date, user_context: User
):
    _set_schema(schema)

    schema_config = (
        db.session.query(SchemaConfig).filter(SchemaConfig.schemaName == schema).first()
    )
    ignore_segments = []
    if schema_config.config:
        ignore_segments = schema_config.config.get("admissionCalc", {}).get(
            "ignoreSegments", []
        )

    last_prescription = get_last_prescription(
        admission_number, ignore_segments=ignore_segments
    )

    if last_prescription == None or last_prescription.idSegment == None:
        raise ValidationError(
            "Não foi possível encontrar o segmento deste atendimento",
            "errors.invalidSegment",
            status.HTTP_400_BAD_REQUEST,
        )

    p_id = prescriptionutils.gen_agg_id(
        admission_number, last_prescription.idSegment, p_date
    )

    agg_p = db.session.query(Prescription).filter(Prescription.id == p_id).first()

    if agg_p is None:
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
        db.session.add(agg_p)

        _audit_create(prescription=agg_p)

    agg_data = prescription_view_service.static_get_prescription(
        id_prescription=agg_p.id, user_context=user_context
    )

    # force reload prescription to get updated data from trigger
    db.session.expire(agg_p)
    agg_p = db.session.query(Prescription).filter(Prescription.id == p_id).first()

    if not agg_p.idSegment:
        # fix segment issue caused by trigger
        agg_p.idSegment = last_prescription.idSegment

    features = prescriptionutils.getFeatures(
        result=agg_data, agg_date=agg_p.date, intervals_for_agg_date=True
    )
    score_variation = _get_score_variation(prescription=agg_p, features=features)
    features.update({"scoreVariation": score_variation})

    agg_p.features = features
    agg_p.aggDrugs = agg_p.features["drugIDs"]
    agg_p.aggDeps = agg_p.features["departmentList"]
    agg_p.update = datetime.today()
    db.session.flush()

    internal_prescription_ids = internal_prescription_ids = (
        prescriptionutils.get_internal_prescription_ids(result=agg_data)
    )

    _log_processed_date(id_prescription_array=internal_prescription_ids, schema=schema)
    _automatic_check(prescription=agg_p, features=features, user_context=user_context)


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


def _set_schema(schema):
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


def get_last_prescription(admission_number, ignore_segments=None):
    query = (
        db.session.query(Prescription)
        .filter(Prescription.admissionNumber == admission_number)
        .filter(Prescription.agg == None)
        .filter(Prescription.concilia == None)
        .filter(Prescription.idSegment != None)
    )

    if ignore_segments:
        query = query.filter(~Prescription.idSegment.in_(ignore_segments))

    return query.order_by(desc(Prescription.date)).first()


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


def _get_processed_status(id_prescription: int):
    query = (
        select(
            PrescriptionDrug.id, func.count(PrescriptionDrugAudit.id).label("p_count")
        )
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
    )

    results = db.session.execute(query).all()

    not_processed_count = 0
    for r in results:
        if r.p_count == 0:
            not_processed_count += 1

    if not_processed_count == len(results):
        return "NEW_PRESCRIPTION"

    if not_processed_count > 0:
        return "NEW_ITENS"

    return "PROCESSED"


def _update_patient_conciliation_status(prescription: Prescription):
    patient = (
        db.session.query(Patient)
        .filter(Patient.admissionNumber == prescription.admissionNumber)
        .first()
    )

    if (
        patient
        and patient.st_conciliation == PatientConciliationStatusEnum.PENDING.value
    ):
        update_concilia_status = False
        if prescription.concilia != None:
            update_concilia_status = True
        else:
            conciliation = (
                db.session.query(Prescription)
                .filter(Prescription.admissionNumber == prescription.admissionNumber)
                .filter(Prescription.concilia != None)
                .first()
            )
            if conciliation:
                update_concilia_status = True

        if update_concilia_status:
            patient.st_conciliation = PatientConciliationStatusEnum.CREATED.value
            db.session.flush()


def _get_score_variation(prescription: Prescription, features: dict):
    new_score = int(features.get("globalScore", 0))
    initial_value = {
        "variation": 100,
        "currentGlobalScore": new_score,
        "previousGlobalScore": 0,
    }

    previous_prescription = (
        db.session.query(Prescription)
        .filter(
            Prescription.id
            == prescriptionutils.gen_agg_id(
                admission_number=prescription.admissionNumber,
                id_segment=prescription.idSegment,
                pdate=prescription.date - timedelta(days=1),
            )
        )
        .first()
    )

    if not previous_prescription:
        return initial_value

    previous_score = int(previous_prescription.features.get("globalScore", 0))
    if previous_score == 0:
        return initial_value

    variation = (new_score - previous_score) / previous_score * 100

    variation_data = initial_value
    variation_data.update(
        {"variation": round(variation, 2), "previousGlobalScore": previous_score}
    )

    return variation_data


def _audit_create(prescription: Prescription):
    a = PrescriptionAudit()
    a.auditType = PrescriptionAuditTypeEnum.CREATE_AGG.value
    a.admissionNumber = prescription.admissionNumber
    a.idPrescription = prescription.id
    a.prescriptionDate = prescription.date
    a.idDepartment = prescription.idDepartment
    a.idSegment = prescription.idSegment

    a.totalItens = -1

    a.agg = prescription.agg
    a.concilia = prescription.concilia
    a.bed = prescription.bed
    a.extra = None
    a.createdAt = datetime.today()
    a.createdBy = 0

    db.session.add(a)


def _automatic_check(prescription: Prescription, features: dict, user_context: User):
    # automatic check prescription if there are no items with validation (drugs, solutions, procedures)
    if (
        features.get("totalItens") == 0
        and prescription.status != "s"
        and feature_service.has_feature(
            FeatureEnum.AUTOMATIC_CHECK_IF_NOT_VALIDATED_ITENS
        )
    ):
        prescription_check_service.check_prescription(
            idPrescription=prescription.id,
            p_status="s",
            user_context=user_context,
            evaluation_time=0,
            alerts=[],
            service_user=False,
            fast_check=True,
        )
